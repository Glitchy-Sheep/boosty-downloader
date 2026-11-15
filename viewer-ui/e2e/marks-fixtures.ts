import { spawn, type ChildProcess } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  stat,
  writeFile,
} from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'

import { expect, test as base, type PostCorpus } from './post-fixtures'

const repository = fileURLToPath(new URL('../../', import.meta.url))
const python = path.join(
  repository,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)

type ContentFile = { sha256: string; modifiedNs: string }

async function contentFiles(library: string): Promise<Record<string, ContentFile>> {
  const root = path.join(library, 'marks_checks')
  const records: Record<string, ContentFile> = {}
  for (const name of (await readdir(root, { recursive: true })).sort()) {
    if (path.basename(name) === 'viewer.json') continue
    const file = path.join(root, name)
    const info = await stat(file, { bigint: true })
    if (!info.isFile()) continue
    records[name] = {
      sha256: createHash('sha256')
        .update(await readFile(file))
        .digest('hex'),
      modifiedNs: info.mtimeNs.toString(),
    }
  }
  return records
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
  if (!address || typeof address === 'string') throw new Error('No marks-test port was allocated')
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

async function ready(server: ChildProcess, marks: PostCorpus): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (server.exitCode !== null || server.signalCode !== null)
      throw new Error('Marks fixture viewer exited before readiness')
    const response = await fetch(`${marks.origin}/api/opener`, {
      signal: AbortSignal.timeout(1_000),
    }).catch(() => undefined)
    if (response?.ok) {
      const capability = (await response.json()) as { root: string }
      if (capability.root !== marks.library)
        throw new Error('Marks fixture port belongs to another library')
      return
    }
    await delay(100)
  }
  throw new Error('Marks fixture viewer did not become ready')
}

/** Each mutation scenario owns its canonical marks and disposable index. */
export const test = base.extend<{ marks: PostCorpus }>({
  marks: async ({ corpus }, provideMarks, info) => {
    const temporary = await mkdtemp(path.join(await realpath(tmpdir()), 'boosty-marks-e2e-'))
    const marks = {
      origin: `http://127.0.0.1:${await unusedPort()}`,
      library: path.join(temporary, 'library'),
      openerLog: path.join(temporary, 'opener.jsonl'),
    }
    let server: ChildProcess | undefined
    let output = ''
    try {
      await cp(corpus.library, marks.library, {
        recursive: true,
        preserveTimestamps: true,
        filter: (source) =>
          !/^\.boosty-downloader\/index\.db(?:-(?:wal|shm|journal))?$/.test(
            path.relative(corpus.library, source).split(path.sep).join('/'),
          ),
      })
      const contentBefore = await contentFiles(marks.library)
      server = spawn(
        python,
        [
          '-m',
          'boosty_downloader.main',
          'view',
          '-o',
          marks.library,
          '--port',
          new URL(marks.origin).port,
          '--no-open',
        ],
        {
          cwd: repository,
          env: {
            ...process.env,
            BOOSTY_VIEWER_OPEN_LOG: marks.openerLog,
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
      await ready(server, marks)
      await provideMarks(marks)
      expect(await contentFiles(marks.library), 'Marking preserves content and media').toEqual(
        contentBefore,
      )
    } finally {
      if (server) await stop(server)
      await mkdir(info.outputDir, { recursive: true })
      await writeFile(info.outputPath('marks-server.log'), output)
      await rm(temporary, { recursive: true, force: true })
    }
  },
  runtimeErrors: async ({ page, marks }, provideRuntime) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.route('**/*', (route) => {
      if (new URL(route.request().url()).origin === marks.origin) return route.continue()
      errors.push(`Unexpected external request: ${route.request().url()}`)
      return route.abort()
    })
    await provideRuntime()
    expect(errors, 'No runtime errors or external requests').toEqual([])
    expect(await readFile(marks.openerLog, 'utf8').catch(() => '')).toBe('')
  },
})

export { expect }
