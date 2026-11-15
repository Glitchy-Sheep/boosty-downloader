import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import type { Page, Route, TestInfo } from '@playwright/test'
import { expect } from '../../e2e/media-fixtures'
import {
  switchFrames,
  type SwitchCaptureWindow,
  type SwitchFrame,
  type TabAction,
} from '../../e2e/media-frames'

export type Variant = 'normal' | 'delayed'
export type Scenario = 'retained-dom' | 'slow-media'
type ImageFile = { suffix: string; bytes: number; sha256: string }
type RequestRecord = { path: string; interceptedAt: number; continuedAt: number | null }
type LoadEvent = { path: string; time: number; width: number; complete: boolean }
type ProbeState = {
  variant: Variant
  scenario: Scenario
  repeat: number
  targets: ImageFile[]
  firstCapture: boolean
}
const states = new WeakMap<Page, ProbeState>()

declare global {
  interface Window {
    imagePairLoads?: LoadEvent[]
  }
}

export async function preparePair(
  page: Page,
  library: string,
  variant: Variant,
  scenario: Scenario,
  repeat: number,
  info: TestInfo,
): Promise<void> {
  const numbers = scenario === 'retained-dom' ? [1, 2, 3, 4, 5] : [2, 3, 4, 5, 6]
  const files = await readdir(path.join(library, 'media_checks'), { recursive: true })
  const targets = await Promise.all(
    numbers.map(async (number) => {
      const name = `Photo ${String(number).padStart(2, '0')} B !'() # 100%25.png`
      const matches = files.filter((file) => file.endsWith(`/media/${name}`))
      if (matches.length !== 1) throw new Error(`Expected one canonical original: ${name}`)
      const body = await readFile(path.join(library, 'media_checks', matches[0]!))
      return {
        suffix: `/media/${name}`,
        bytes: body.length,
        sha256: createHash('sha256').update(body).digest('hex'),
      }
    }),
  )
  states.set(page, { variant, scenario, repeat, targets, firstCapture: true })
  await page.addInitScript(
    (suffixes: string[]) => {
      window.imagePairLoads = []
      document.addEventListener(
        'load',
        (event) => {
          const image = event.target
          if (!(image instanceof HTMLImageElement)) return
          const pathname = decodeURIComponent(new URL(image.currentSrc || image.src).pathname)
          if (
            !pathname.startsWith('/media/media_checks/') ||
            !suffixes.some((suffix) => pathname.endsWith(suffix))
          )
            return
          if (window.imagePairLoads!.length < 32)
            window.imagePairLoads!.push({
              path: pathname,
              time: performance.now(),
              width: image.naturalWidth,
              complete: image.complete,
            })
        },
        true,
      )
    },
    targets.map((target) => target.suffix),
  )
  await info.attach('image-pair-manifest.json', {
    body: JSON.stringify({ variant, scenario, repeat, targets }),
    contentType: 'application/json',
  })
}

async function completedImages(page: Page, suffixes: string[]) {
  return page.evaluate(async (suffixes) => {
    const matches = (pathname: string) =>
      pathname.startsWith('/media/media_checks/') &&
      suffixes.some((suffix) => pathname.endsWith(suffix))
    const images = [...document.images].filter((image) =>
      matches(decodeURIComponent(new URL(image.currentSrc || image.src).pathname)),
    )
    const decoded = await Promise.all(
      images.map(async (image) => {
        const requestedAt = performance.now()
        let timer: ReturnType<typeof setTimeout> | undefined
        const timeout = new Promise<string>((resolve) => {
          timer = setTimeout(() => resolve('timeout'), 5000)
        })
        const status = await Promise.race([
          image.decode().then(
            () => 'decoded',
            () => 'error',
          ),
          timeout,
        ])
        clearTimeout(timer)
        return {
          path: decodeURIComponent(new URL(image.currentSrc || image.src).pathname),
          requestedAt,
          resolvedAt: performance.now(),
          status,
          complete: image.complete,
          width: image.naturalWidth,
        }
      }),
    )
    const resources = performance
      .getEntriesByType('resource')
      .filter((entry) => matches(decodeURIComponent(new URL(entry.name).pathname)))
      .map((entry) => {
        const resource = entry as PerformanceResourceTiming
        return {
          path: decodeURIComponent(new URL(resource.name).pathname),
          startTime: resource.startTime,
          responseStart: resource.responseStart,
          responseEnd: resource.responseEnd,
          transferSize: resource.transferSize,
          decodedBodySize: resource.decodedBodySize,
        }
      })
    return {
      timeOrigin: performance.timeOrigin,
      finishedAt: performance.now(),
      loads: window.imagePairLoads ?? [],
      decoded,
      resources,
    }
  }, suffixes)
}

export async function recordSwitch(
  page: Page,
  action: TabAction,
  info: TestInfo,
  name: string,
  capture: SwitchCaptureWindow = {},
): Promise<SwitchFrame[]> {
  const state = states.get(page)
  if (!state) throw new Error('Missing private pair state')
  if (!state.firstCapture) {
    const { frames, diagnostics } = await switchFrames(page, action, capture)
    await info.attach(`${name}-frames.json`, {
      body: JSON.stringify(frames),
      contentType: 'application/json',
    })
    await info.attach(`${name}-performance.json`, {
      body: JSON.stringify(diagnostics),
      contentType: 'application/json',
    })
    return frames
  }
  state.firstCapture = false
  const suffixes = state.targets.map((target) => target.suffix)
  const matches = (url: URL): boolean => {
    const pathname = decodeURIComponent(url.pathname)
    return (
      pathname.startsWith('/media/media_checks/') &&
      suffixes.some((suffix) => pathname.endsWith(suffix))
    )
  }
  const requests: RequestRecord[] = []
  let releasePromise: (() => void) | undefined
  const held = new Promise<void>((resolve) => {
    releasePromise = resolve
  })
  let releaseReason: string | null = null
  let releasedAt: number | null = null
  const release = (reason: string): void => {
    if (releaseReason !== null) return
    releaseReason = reason
    releasedAt = performance.now()
    releasePromise!()
  }
  const handler = async (route: Route): Promise<void> => {
    const record = {
      path: decodeURIComponent(new URL(route.request().url()).pathname),
      interceptedAt: performance.now(),
      continuedAt: null,
    } as RequestRecord
    requests.push(record)
    if (state.variant === 'delayed') await held
    record.continuedAt = performance.now()
    await route.continue()
  }
  await page.route(matches, handler)
  const captureStartedAt = performance.now()
  const watchdog = setTimeout(() => release('watchdog'), 5000)
  let recording: Awaited<ReturnType<typeof switchFrames>>
  try {
    recording = await switchFrames(page, action, capture)
  } finally {
    release('capture-finished-or-error')
    clearTimeout(watchdog)
    await page.unroute(matches, handler)
  }
  await info.attach(`${name}-frames.json`, {
    body: JSON.stringify(recording.frames),
    contentType: 'application/json',
  })
  await info.attach(`${name}-performance.json`, {
    body: JSON.stringify(recording.diagnostics),
    contentType: 'application/json',
  })
  const completion = await completedImages(page, suffixes)
  await info.attach('image-delivery.json', {
    body: JSON.stringify({
      variant: state.variant,
      scenario: state.scenario,
      repeat: state.repeat,
      captureStartedAt,
      releasedAt,
      releaseReason,
      requests,
      completion,
    }),
    contentType: 'application/json',
  })
  expect(releaseReason, 'A watchdog release invalidates this ablation').toBe(
    'capture-finished-or-error',
  )
  expect(
    requests,
    'Exactly the five known original image requests must be controlled',
  ).toHaveLength(5)
  expect(new Set(requests.map((request) => request.path)).size).toBe(5)
  expect(completion.decoded).toHaveLength(5)
  expect(
    completion.decoded.every(
      (image) => image.status === 'decoded' && image.complete && image.width > 0,
    ),
  ).toBe(true)
  return recording.frames
}
