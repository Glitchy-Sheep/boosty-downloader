import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { access, mkdir, mkdtemp, realpath, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

import type { FullConfig } from '@playwright/test'

const run = promisify(execFile)
const repository = fileURLToPath(new URL('../../', import.meta.url))
const python = path.join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')

async function unusedPort(): Promise<number> {
  const probe = createServer()
  await new Promise<void>((resolve, reject) => {
    probe.once('error', reject)
    probe.listen(0, '127.0.0.1', resolve)
  })
  const address = probe.address()
  await new Promise<void>((resolve, reject) => probe.close(error => error ? reject(error) : resolve()))
  if (address === null || typeof address === 'string') throw new Error('No local test port was allocated')
  return address.port
}

async function stop(server: ChildProcess): Promise<void> {
  if (server.pid === undefined || server.exitCode !== null || server.signalCode !== null) return
  const exited = new Promise<void>(resolve => server.once('exit', () => resolve()))
  server.kill('SIGTERM')
  await Promise.race([exited, delay(5_000, undefined, { ref: false })])
  if (server.exitCode === null && server.signalCode === null) server.kill('SIGKILL')
  await exited
}

async function waitForViewer(server: ChildProcess, origin: string, library: string): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null || server.signalCode !== null) throw new Error('The test viewer exited before readiness')
    const response = await fetch(`${origin}/api/opener`, { signal: AbortSignal.timeout(1_000) }).catch(() => undefined)
    if (response?.ok) {
      const capability = await response.json() as { root: string | null }
      if (capability.root === null || await realpath(capability.root) !== await realpath(library)) {
        throw new Error('The test port belongs to a different library')
      }
      return
    }
    await delay(100)
  }
  throw new Error('The test viewer did not become ready')
}

export default async function setup(config: FullConfig): Promise<() => Promise<void>> {
  await access(python)
  await access(path.join(repository, 'boosty_downloader/viewer/static/app/index.html'))
  const temporary = await mkdtemp(path.join(await realpath(tmpdir()), 'boosty-viewer-e2e-'))
  const library = path.join(temporary, 'library')
  let generator: ChildProcess | undefined
  let server: ChildProcess | undefined
  let output = ''
  let cleanup: Promise<void> | undefined
  const teardown = (): Promise<void> => cleanup ??= (async () => {
    process.off('SIGINT', interrupt)
    process.off('SIGTERM', terminate)
    if (generator) await stop(generator)
    if (server) await stop(server)
    try {
      await mkdir(config.projects[0].outputDir, { recursive: true })
      await writeFile(path.join(config.projects[0].outputDir, 'viewer-server.log'), output)
    } finally {
      await rm(temporary, { recursive: true, force: true })
    }
  })()
  const interrupt = (): void => { void teardown().finally(() => process.exit(130)) }
  const terminate = (): void => { void teardown().finally(() => process.exit(143)) }
  process.once('SIGINT', interrupt)
  process.once('SIGTERM', terminate)
  try {
    const preparation = run(python, [path.join(repository, 'scripts/viewer_e2e_sample.py'), library], {
      cwd: repository, timeout: 120_000,
    })
    generator = preparation.child
    await preparation
    const origin = `http://127.0.0.1:${await unusedPort()}`
    server = spawn(python, ['-m', 'boosty_downloader.main', 'view', '-o', library,
      '--port', new URL(origin).port, '--no-open'], {
      cwd: repository,
      env: { ...process.env, BOOSTY_VIEWER_OPEN_LOG: path.join(temporary, 'open-actions.jsonl'), PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const collect = (chunk: Buffer): void => { output = (output + chunk.toString()).slice(-32_000) }
    server.stdout?.on('data', collect)
    server.stderr?.on('data', collect)
    server.on('error', error => { output += error.message })
    await waitForViewer(server, origin, library)
    process.env.BOOSTY_VIEWER_E2E_ORIGIN = origin
    process.env.BOOSTY_VIEWER_E2E_LIBRARY = library
    return teardown
  } catch (error) {
    await teardown()
    throw new Error(`Cannot start the isolated test viewer:\n${output}`, { cause: error })
  }
}
