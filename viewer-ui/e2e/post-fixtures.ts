import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

import { expect, test as base, type Locator, type Page } from '@playwright/test'

import type { Author, MediaItem, PostDetail, PostList } from '../src/lib/api.gen'

const run = promisify(execFile)
const repository = fileURLToPath(new URL('../../', import.meta.url))
const python = path.join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')

export const AUTHOR = 'reader_checks'
export const API_PATH = `/api/authors/${AUTHOR}`
export const POSTS = {
  before: '00000000-0000-4000-8000-000000000001',
  reader: '00000000-0000-4000-8000-000000000002',
  after: '00000000-0000-4000-8000-000000000003',
  favorite: '00000000-0000-4000-8000-000000000010',
  playback: '00000000-0000-4000-8000-000000000011',
  retained: '00000000-0000-4000-8000-000000000012',
  locked: '00000000-0000-4000-8000-000000000013',
  finished: '00000000-0000-4000-8000-000000000014',
  boundary: '00000000-0000-4000-8000-000000000015',
  security: '00000000-0000-4000-8000-000000000016',
} as const

export type PostCorpus = { origin: string; library: string; openerLog: string }

async function unusedPort(): Promise<number> {
  const probe = createServer()
  await new Promise<void>((resolve, reject) => { probe.once('error', reject); probe.listen(0, '127.0.0.1', resolve) })
  const address = probe.address()
  await new Promise<void>((resolve, reject) => probe.close(error => error ? reject(error) : resolve()))
  if (!address || typeof address === 'string') throw new Error('No browser-test port was allocated')
  return address.port
}

async function stop(server: ChildProcess): Promise<void> {
  if (!server.pid || server.exitCode !== null || server.signalCode !== null) return
  const exited = new Promise<void>(resolve => server.once('exit', () => resolve()))
  server.kill('SIGTERM')
  await Promise.race([exited, delay(5_000, undefined, { ref: false })])
  if (server.exitCode === null && server.signalCode === null) server.kill('SIGKILL')
  await exited
}

async function ready(server: ChildProcess, corpus: PostCorpus): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null || server.signalCode !== null) throw new Error('Post fixture viewer exited before readiness')
    const response = await fetch(`${corpus.origin}/api/opener`, { signal: AbortSignal.timeout(1_000) }).catch(() => undefined)
    if (response?.ok) {
      const capability = await response.json() as { root: string }
      if (capability.root !== corpus.library) throw new Error('Post fixture port belongs to another library')
      return
    }
    await delay(100)
  }
  throw new Error('Post fixture viewer did not become ready')
}

export const test = base.extend<{ runtimeErrors: void }, { corpus: PostCorpus }>({
  corpus: [async ({ browserName }, provideCorpus, worker) => {
    const temporary = await mkdtemp(path.join(await realpath(tmpdir()), 'boosty-post-e2e-'))
    const corpus = { origin: `http://127.0.0.1:${await unusedPort()}`, library: path.join(temporary, 'library'), openerLog: path.join(temporary, 'opener.jsonl') }
    let server: ChildProcess | undefined
    let output = ''
    try {
      await run(python, [path.join(repository, 'scripts/viewer_post_e2e_sample.py'), corpus.library], { cwd: repository, timeout: 120_000 })
      server = spawn(python, ['-m', 'boosty_downloader.main', 'view', '-o', corpus.library, '--port', new URL(corpus.origin).port, '--no-open'], {
        cwd: repository, env: { ...process.env, BOOSTY_VIEWER_OPEN_LOG: corpus.openerLog, PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'],
      })
      const collect = (chunk: Buffer): void => { output = (output + chunk.toString()).slice(-32_000) }
      server.stdout?.on('data', collect)
      server.stderr?.on('data', collect)
      await ready(server, corpus)
      await provideCorpus(corpus)
    } finally {
      if (server) await stop(server)
      await mkdir(worker.project.outputDir, { recursive: true })
      await writeFile(path.join(worker.project.outputDir, `post-server-${browserName}-${worker.workerIndex}.log`), output)
      await rm(temporary, { recursive: true, force: true })
    }
  }, { scope: 'worker' }],
  runtimeErrors: [async ({ page, corpus }, use) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin === corpus.origin) return route.continue()
      errors.push(`Unexpected external request: ${route.request().url()}`)
      return route.abort()
    })
    await use()
    expect(errors, 'No runtime errors or external requests').toEqual([])
    expect(await readFile(corpus.openerLog, 'utf8').catch(() => '')).toBe('')
  }, { auto: true }],
})
export { expect }

export function postPath(id: string, search = ''): string {
  return `/a/${AUTHOR}/p/${id}${search ? `?${search}` : ''}`
}

export function pane(page: Page): Locator {
  return page.getByRole('region', { name: 'Selected post', exact: true })
}

export function sidebar(page: Page): Locator {
  return page.getByRole('complementary', { name: 'Posts of Post Reader Checks' })
}

export async function detail(page: Page, corpus: PostCorpus, id: string): Promise<PostDetail> {
  const response = await page.request.get(`${corpus.origin}${API_PATH}/posts/${id}`)
  expect(response.ok()).toBe(true)
  return await response.json() as PostDetail
}

export async function list(page: Page, corpus: PostCorpus, search = ''): Promise<PostList> {
  const response = await page.request.get(`${corpus.origin}${API_PATH}/posts${search ? `?${search}` : ''}`)
  expect(response.ok()).toBe(true)
  return await response.json() as PostList
}

export async function author(page: Page, corpus: PostCorpus): Promise<Author> {
  const response = await page.request.get(`${corpus.origin}${API_PATH}`)
  expect(response.ok()).toBe(true)
  return await response.json() as Author
}

export async function openPost(page: Page, corpus: PostCorpus, id: string, search = ''): Promise<PostDetail> {
  const post = await detail(page, corpus, id)
  await page.goto(`${corpus.origin}${postPath(id, search)}`)
  await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText(post.title)
  return post
}

export async function readyPlayer(player: Locator): Promise<void> {
  await expect.poll(() => player.evaluate((media: HTMLMediaElement) => media.readyState >= 1 && Number.isFinite(media.duration) && media.duration > 0)).toBe(true)
}

export async function storedMedia(page: Page, corpus: PostCorpus, postId: string, kind: MediaItem['kind']): Promise<MediaItem> {
  const media = (await detail(page, corpus, postId)).media.find(item => item.kind === kind)
  if (!media) throw new Error(`Missing ${kind} in ${postId}`)
  return media
}
