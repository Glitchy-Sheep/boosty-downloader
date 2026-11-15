import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

import { expect, test as base, type Locator, type Page } from '@playwright/test'

import type { MediaPage, PostDetail, PostList } from '../src/lib/api.gen'

const run = promisify(execFile)
const repository = fileURLToPath(new URL('../../', import.meta.url))
const python = path.join(
  repository,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)

export const AUTHOR = 'media_checks'
export const GALLERY = 'gallery_checks'
export const REMOVED = 'removed_checks'
export const API_PATH = `/api/authors/${AUTHOR}`

export type MediaCorpus = { origin: string; library: string; openerLog: string }

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
  if (!address || typeof address === 'string') throw new Error('No browser-test port was allocated')
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
      throw new Error('Media fixture viewer exited before readiness')
    const response = await fetch(`${corpus.origin}/api/opener`, {
      signal: AbortSignal.timeout(1_000),
    }).catch(() => undefined)
    if (response?.ok) {
      const capability = (await response.json()) as { root: string }
      if (capability.root !== corpus.library)
        throw new Error('Media fixture port belongs to another library')
      return
    }
    await delay(100)
  }
  throw new Error('Media fixture viewer did not become ready')
}

export const test = base.extend<{ runtimeErrors: void }, { corpus: MediaCorpus }>({
  corpus: [
    async ({ browserName }, provideCorpus, worker) => {
      const temporary = await mkdtemp(path.join(await realpath(tmpdir()), 'boosty-media-e2e-'))
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
          [path.join(repository, 'scripts/viewer_media_e2e_sample.py'), corpus.library],
          { cwd: repository, timeout: 120_000 },
        )
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
      } finally {
        if (server) await stop(server)
        await mkdir(worker.project.outputDir, { recursive: true })
        await writeFile(
          path.join(
            worker.project.outputDir,
            `media-server-${browserName}-${worker.workerIndex}.log`,
          ),
          output,
        )
        await rm(temporary, { recursive: true, force: true })
      }
    },
    { scope: 'worker' },
  ],
  runtimeErrors: [
    async ({ page, corpus }, use) => {
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      await page.route('**/*', (route) => {
        if (new URL(route.request().url()).origin === corpus.origin) return route.continue()
        errors.push(`Unexpected external request: ${route.request().url()}`)
        return route.abort()
      })
      await use()
      expect(errors, 'No runtime errors or external requests').toEqual([])
      expect(await readFile(corpus.openerLog, 'utf8').catch(() => '')).toBe('')
    },
    { auto: true },
  ],
})
export { expect }

export function postId(number: number): string {
  return `40000000-0000-4000-8000-${String(number).padStart(12, '0')}`
}

export function mediaPath(author = AUTHOR, search = ''): string {
  return `/a/${author}/media${search ? `?${search}` : ''}`
}

export function postPath(number = 1, search = '', author = AUTHOR): string {
  return `/a/${author}/p/${postId(number)}${search ? `?${search}` : ''}`
}

export async function inventory(
  page: Page,
  corpus: MediaCorpus,
  search = '',
  author = AUTHOR,
): Promise<MediaPage> {
  const params = new URLSearchParams(search)
  params.delete('open')
  const query = params.toString()
  const response = await page.request.get(
    `${corpus.origin}/api/authors/${author}/media${query ? `?${query}` : ''}`,
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as MediaPage
}

export async function detail(
  page: Page,
  corpus: MediaCorpus,
  number = 1,
  author = AUTHOR,
): Promise<PostDetail> {
  const response = await page.request.get(
    `${corpus.origin}/api/authors/${author}/posts/${postId(number)}`,
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as PostDetail
}

export async function listing(
  page: Page,
  corpus: MediaCorpus,
  search = '',
  author = AUTHOR,
): Promise<PostList> {
  const response = await page.request.get(
    `${corpus.origin}/api/authors/${author}/posts${search ? `?${search}` : ''}`,
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as PostList
}

export function scroller(page: Page): Locator {
  return page.locator('[data-media-scroller]')
}

export function pane(page: Page, tab: 'posts' | 'media'): Locator {
  return page.locator(`.author-pane[data-tab="${tab}"]`)
}

export async function openMedia(
  page: Page,
  corpus: MediaCorpus,
  search = '',
  author = AUTHOR,
): Promise<MediaPage> {
  const data = await inventory(page, corpus, search, author)
  await page.goto(`${corpus.origin}${mediaPath(author, search)}`)
  await expect(pane(page, 'media')).toBeVisible()
  await expect(pane(page, 'media').locator('[data-media-id]').first()).toBeVisible()
  return data
}

export async function openPost(
  page: Page,
  corpus: MediaCorpus,
  number = 1,
  search = '',
  author = AUTHOR,
): Promise<void> {
  await page.goto(`${corpus.origin}${postPath(number, search, author)}`)
  await expect(pane(page, 'posts').getByRole('heading', { level: 1 })).toHaveText(
    `Media post ${String(number).padStart(2, '0')}`,
  )
}

export async function tab(page: Page, name: 'Posts' | 'Media'): Promise<void> {
  await page
    .getByRole('navigation', { name: 'Author', exact: true })
    .getByRole('link', { name, exact: true })
    .click()
  await expect(pane(page, name === 'Posts' ? 'posts' : 'media')).toBeVisible()
}

export async function readyPlayer(player: Locator): Promise<void> {
  await expect
    .poll(() =>
      player.evaluate(
        (media: HTMLMediaElement) =>
          media.readyState >= 1 && Number.isFinite(media.duration) && media.duration > 0,
      ),
    )
    .toBe(true)
}

export async function resetMarks(
  page: Page,
  corpus: MediaCorpus,
  number: number,
  favorite = true,
): Promise<void> {
  const root = `${corpus.origin}${API_PATH}/posts/${postId(number)}`
  expect((await page.request.put(`${root}/marks`, { data: { favorite } })).ok()).toBe(true)
  expect((await page.request.put(`${root}/marks`, { data: { seen: false } })).ok()).toBe(true)
}
