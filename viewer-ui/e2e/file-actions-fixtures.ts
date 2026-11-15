import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, realpath, rm, stat, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

import { expect, test as base, type Locator, type Page } from '@playwright/test'

import type { MediaItem, MediaPage, OpenerCapabilities, PostDetail } from '../src/lib/api.gen'
import { inventory, type MediaCorpus } from './media-fixtures'
import { requireFixture } from './required-fixture'

const run = promisify(execFile)
const repository = fileURLToPath(new URL('../../', import.meta.url))
const python = path.join(
  repository,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)

export const AUTHOR = 'file_action_checks'
export const API_PATH = `/api/authors/${AUTHOR}`
export type OpenRecord = { action: 'open' | 'reveal'; path: string }
export type Recording = { expected: OpenRecord[]; before: number }
export type RuntimeCheck = { assertClean: () => void }

export async function watchRuntime(page: Page, corpus: MediaCorpus): Promise<RuntimeCheck> {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/*', (route) => {
    if (new URL(route.request().url()).origin === corpus.origin) return route.continue()
    errors.push(`Unexpected external request: ${route.request().url()}`)
    return route.abort()
  })
  return {
    assertClean: () => expect(errors, 'No runtime errors or external requests').toEqual([]),
  }
}

async function unusedPort(): Promise<number> {
  const probe = createServer()
  await new Promise<void>((resolve, reject) => {
    probe.once('error', reject)
    probe.listen(0, '127.0.0.1', resolve)
  })
  const address = probe.address()
  await new Promise<void>((resolve, reject) =>
    probe.close((error) => (error ? reject(error) : resolve())),
  )
  if (!address || typeof address === 'string')
    throw new Error('No file-action test port was allocated')
  return address.port
}

async function stop(server: ChildProcess): Promise<void> {
  if (!server.pid || server.exitCode !== null || server.signalCode !== null) return
  const exited = new Promise<void>((resolve) => server.once('exit', () => resolve()))
  server.kill('SIGTERM')
  await Promise.race([exited, delay(5_000, undefined, { ref: false })])
  if (server.exitCode === null && server.signalCode === null) server.kill('SIGKILL')
  await exited
}

async function ready(server: ChildProcess, corpus: MediaCorpus): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null || server.signalCode !== null)
      throw new Error('File-action viewer exited before readiness')
    const response = await fetch(`${corpus.origin}/api/opener`, {
      signal: AbortSignal.timeout(1_000),
    }).catch(() => undefined)
    if (response?.ok) {
      const capabilities = (await response.json()) as OpenerCapabilities
      if (capabilities.root !== corpus.library)
        throw new Error('File-action port belongs to another library')
      return
    }
    await delay(100)
  }
  throw new Error('File-action viewer did not become ready')
}

async function fileSnapshot(
  corpus: MediaCorpus,
): Promise<Record<string, { sha256: string; mtime: number }>> {
  const sources = JSON.parse(
    await readFile(
      path.join(corpus.library, '.boosty-downloader/file-action-sources.json'),
      'utf8',
    ),
  ) as Record<string, string>
  const snapshot: Record<string, { sha256: string; mtime: number }> = {}
  for (const [destination, source] of Object.entries(sources)) {
    const bytes = await readFile(path.join(corpus.library, destination))
    expect(bytes, destination).toEqual(await readFile(path.join(corpus.library, source)))
    snapshot[destination] = {
      sha256: createHash('sha256').update(bytes).digest('hex'),
      mtime: (await stat(path.join(corpus.library, destination))).mtimeMs,
    }
  }
  return snapshot
}

export async function opened(corpus: MediaCorpus): Promise<OpenRecord[]> {
  const contents = await readFile(corpus.openerLog, 'utf8').catch(() => '')
  return contents
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line) as OpenRecord)
}

export const test = base.extend<
  { recording: Recording; runtimeErrors: void },
  { corpus: MediaCorpus }
>({
  corpus: [
    async ({ browserName }, provideCorpus, worker) => {
      const temporary = await mkdtemp(
        path.join(await realpath(tmpdir()), 'boosty-file-actions-e2e-'),
      )
      const corpus = {
        origin: `http://127.0.0.1:${await unusedPort()}`,
        library: path.join(temporary, 'library'),
        openerLog: path.join(temporary, 'opener.jsonl'),
      }
      let server: ChildProcess | undefined
      let output = ''
      try {
        await run(
          python,
          [path.join(repository, 'scripts/viewer_file_actions_e2e_sample.py'), corpus.library],
          { cwd: repository, timeout: 120_000 },
        )
        const before = await fileSnapshot(corpus)
        server = spawn(
          python,
          [
            '-m',
            'boosty_downloader.main',
            'view',
            '-o',
            corpus.library,
            '--port',
            new URL(corpus.origin).port,
            '--no-open',
          ],
          {
            cwd: repository,
            env: {
              ...process.env,
              BOOSTY_VIEWER_OPEN_LOG: corpus.openerLog,
              PYTHONUNBUFFERED: '1',
            },
            stdio: ['ignore', 'pipe', 'pipe'],
          },
        )
        const collect = (chunk: Buffer): void => {
          output = (output + chunk.toString()).slice(-32_000)
        }
        server.stdout?.on('data', collect)
        server.stderr?.on('data', collect)
        await ready(server, corpus)
        await provideCorpus(corpus)
        expect(await fileSnapshot(corpus), 'File bytes and mtimes stay unchanged').toEqual(before)
      } finally {
        if (server) await stop(server)
        await mkdir(worker.project.outputDir, { recursive: true })
        await writeFile(
          path.join(
            worker.project.outputDir,
            `file-actions-server-${browserName}-${worker.workerIndex}.log`,
          ),
          output,
        )
        await rm(temporary, { recursive: true, force: true })
      }
    },
    { scope: 'worker' },
  ],
  recording: [
    async ({ corpus }, use) => {
      const recording = { expected: [], before: (await opened(corpus)).length }
      await use(recording)
      expect(
        (await opened(corpus)).slice(recording.before),
        'Only explicitly expected system actions are recorded',
      ).toEqual(recording.expected)
    },
    { auto: true },
  ],
  runtimeErrors: [
    async ({ page, corpus }, use) => {
      const runtime = await watchRuntime(page, corpus)
      await use()
      runtime.assertClean()
    },
    { auto: true },
  ],
})
export { expect, requireFixture }

export function postId(number = 1): string {
  return `50000000-0000-4000-8000-${String(number).padStart(12, '0')}`
}

export function sourcePath(corpus: MediaCorpus, item: MediaItem): string {
  return path.join(corpus.library, AUTHOR, ...item.path.split('/'))
}

export function sourceUrl(item: MediaItem): string {
  const parts = item.path
    .split('/')
    .map((part) =>
      encodeURIComponent(part).replace(
        /[!'()*]/g,
        (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
      ),
    )
  return `/media/${AUTHOR}/${parts.join('/')}`
}

export function localCapabilities(
  corpus: MediaCorpus,
  overrides: Partial<OpenerCapabilities> = {},
): OpenerCapabilities {
  return {
    open: true,
    reveal: true,
    folders: true,
    root: corpus.library,
    sep: path.sep,
    system: 'macos',
    ...overrides,
  }
}

export function remoteCapabilities(): OpenerCapabilities {
  return { open: false, reveal: false, folders: false, root: null, sep: '/', system: null }
}

export async function capabilities(page: Page, value: OpenerCapabilities): Promise<void> {
  await page.route('**/api/opener', (route) => route.fulfill({ json: value }))
}

export async function openFiles(page: Page, corpus: MediaCorpus): Promise<MediaPage> {
  const data = await inventory(page, corpus, 'view=files', AUTHOR)
  await page.goto(`${corpus.origin}/a/${AUTHOR}/media?view=files`)
  await expect(page.locator('[data-media-id]').first()).toBeVisible()
  return data
}

export async function openPost(page: Page, corpus: MediaCorpus, number = 1): Promise<PostDetail> {
  const response = await page.request.get(`${corpus.origin}${API_PATH}/posts/${postId(number)}`)
  expect(response.ok()).toBe(true)
  const post = (await response.json()) as PostDetail
  await page.goto(`${corpus.origin}/a/${AUTHOR}/p/${post.id}`)
  await expect(
    page.getByRole('region', { name: 'Selected post' }).getByRole('heading', { level: 1 }),
  ).toHaveText(post.title)
  return post
}

export async function itemRow(page: Page, data: MediaPage, item: MediaItem): Promise<Locator> {
  const row = page.locator(`[data-media-id="${item.id}"]`)
  if (!(await row.count()))
    await page.locator('[data-media-scroller]').evaluate((element, index) => {
      element.scrollTop = index * 72
    }, data.items.indexOf(item))
  await expect(row).toBeAttached()
  await row.scrollIntoViewIfNeeded()
  return row
}

export function ofType(data: MediaPage, type: MediaItem['file_type'], removed = false): MediaItem {
  return requireFixture(
    data.items.find((item) => item.file_type === type && item.removed === removed),
  )
}

export async function expectOpen(
  corpus: MediaCorpus,
  recording: Recording,
  item: MediaItem | string,
  action: OpenRecord['action'] = 'open',
): Promise<void> {
  recording.expected.push({
    action,
    path: typeof item === 'string' ? item : sourcePath(corpus, item),
  })
  await expect
    .poll(async () => (await opened(corpus)).slice(recording.before))
    .toEqual(recording.expected)
}

export async function expectDownload(
  page: Page,
  corpus: MediaCorpus,
  link: Locator,
  item: MediaItem,
  activation: 'click' | 'tap' = 'click',
): Promise<void> {
  await expect(link).toHaveAttribute('href', sourceUrl(item))
  const download = page.waitForEvent('download')
  await link[activation]()
  const saved = await download
  expect(await saved.failure()).toBeNull()
  expect(await readFile(requireFixture(await saved.path()))).toEqual(
    await readFile(sourcePath(corpus, item)),
  )
}
