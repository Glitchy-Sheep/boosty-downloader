export type TabName = 'posts' | 'media'
export type TabAction = TabName | 'back' | 'forward'
type PaneFrame = { tab: string; opacity: number; x: number; visible: boolean; inert: boolean }
export type SwitchFrame = {
  time: number
  logo: number
  pill: number
  panes: PaneFrame[]
  articleOpacity: number | null
  textLength: number
}

export type SwitchCaptureWindow = { duration?: number; firstMountedPane?: TabName }
type SwitchCaptureOptions = SwitchCaptureWindow & { action: TabAction }
type ObservedEntryType = 'longtask' | 'long-animation-frame'
type SampleTiming = {
  frameIndex: number
  rafTime: number | null
  readStartedAt: number
  readFinishedAt: number
}
type EntryTiming = { name: string; entryType: string; startTime: number; duration: number }
type ScriptTiming = EntryTiming & {
  executionStart: number | null
  forcedStyleAndLayoutDuration: number | null
  pauseDuration: number | null
  sourceURL: string | null
  sourceFunctionName: string | null
  sourceCharPosition: number | null
  invoker: string | null
  invokerType: string | null
  windowAttribution: string | null
}
type AnimationTiming = EntryTiming & {
  renderStart: number | null
  styleAndLayoutStart: number | null
  blockingDuration: number | null
  firstUIEventTimestamp: number | null
  scripts: ScriptTiming[]
  scriptsDropped: number
}
type ResourceTiming = EntryTiming & {
  initiatorType: string
  responseEnd: number
  transferSize: number
  encodedBodySize: number
  decodedBodySize: number
}
type EntryBuffer = {
  entryType: ObservedEntryType
  entries: PerformanceEntry[]
  dropped: number
}
type ActiveObserver = { observer: PerformanceObserver; buffer: EntryBuffer }
type ObserverError = { entryType: ObservedEntryType; message: string }

// LoAF entries are not yet declared by the installed DOM types.
interface ScriptEntry extends PerformanceEntry {
  readonly executionStart?: number
  readonly forcedStyleAndLayoutDuration?: number
  readonly pauseDuration?: number
  readonly sourceURL?: string
  readonly sourceFunctionName?: string
  readonly sourceCharPosition?: number
  readonly invoker?: string
  readonly invokerType?: string
  readonly windowAttribution?: string
}
interface AnimationEntry extends PerformanceEntry {
  readonly renderStart?: number
  readonly styleAndLayoutStart?: number
  readonly blockingDuration?: number
  readonly firstUIEventTimestamp?: number
  readonly scripts?: readonly ScriptEntry[]
}

export type SwitchDiagnostics = {
  timeOrigin: number
  began: number
  ended: number
  observerAvailable: boolean
  supportedEntryTypes: string[]
  observedEntryTypes: ObservedEntryType[]
  observerErrors: ObserverError[]
  limits: {
    entriesPerObserver: number
    sampleTimings: number
    resources: number
    scriptsPerAnimationFrame: number
  }
  samples: SampleTiming[]
  samplesDropped: number
  longTasks: EntryTiming[]
  longAnimationFrames: AnimationTiming[]
  observerEntriesDropped: { entryType: ObservedEntryType; count: number }[]
  resources: ResourceTiming[]
  resourcesDropped: number
}
export type SwitchRecording = { frames: SwitchFrame[]; diagnostics: SwitchDiagnostics }

/** Runs entirely in the page so the sampler and diagnostics share one performance clock. */
export async function captureSwitch({
  action,
  duration = 550,
  firstMountedPane,
}: SwitchCaptureOptions): Promise<SwitchRecording> {
  const limits = {
    entriesPerObserver: 128,
    sampleTimings: 512,
    resources: 512,
    scriptsPerAnimationFrame: 128,
  }
  const frames: SwitchFrame[] = []
  const samples: SampleTiming[] = []
  let samplesDropped = 0
  const observerAvailable = typeof PerformanceObserver !== 'undefined'
  const supportedEntryTypes = observerAvailable ? [...PerformanceObserver.supportedEntryTypes] : []
  const activeObservers: ActiveObserver[] = []
  const observerErrors: ObserverError[] = []
  const observedEntryTypes: ObservedEntryType[] = ['longtask', 'long-animation-frame']
  const collect = (buffer: EntryBuffer, entries: PerformanceEntry[]): void => {
    for (const entry of entries) {
      if (buffer.entries.length < limits.entriesPerObserver) buffer.entries.push(entry)
      else buffer.dropped += 1
    }
  }
  for (const entryType of observedEntryTypes) {
    if (!supportedEntryTypes.includes(entryType)) continue
    const buffer: EntryBuffer = { entryType, entries: [], dropped: 0 }
    const observer = new PerformanceObserver((list) => collect(buffer, list.getEntries()))
    try {
      observer.observe({ type: entryType })
      activeObservers.push({ observer, buffer })
    } catch (error: unknown) {
      observer.disconnect()
      observerErrors.push({
        entryType,
        message: error instanceof Error ? error.message : String(error),
      })
    }
  }

  const began = performance.now()
  let ended = began
  const read = (rafTime: number | null): void => {
    const readStartedAt = performance.now()
    const frameIndex = frames.length
    const article = document.querySelector('.author-pane[data-tab="posts"] article')
    frames.push({
      time: performance.now() - began,
      logo: document.querySelector('a[aria-label="Boosty Library"]')!.getBoundingClientRect().left,
      pill: document.querySelector('.author-tab-pill')!.getBoundingClientRect().left,
      panes: [...document.querySelectorAll<HTMLElement>('.author-pane')].map((pane) => {
        const style = getComputedStyle(pane)
        return {
          tab: pane.dataset.tab ?? '',
          opacity: Number(style.opacity),
          x: new DOMMatrix(style.transform).m41,
          visible: style.visibility === 'visible',
          inert: pane.inert,
        }
      }),
      articleOpacity: article ? Number(getComputedStyle(article).opacity) : null,
      textLength:
        document.querySelector('.author-pane[data-tab="posts"] [aria-label="Selected post"]')
          ?.textContent?.length ?? 0,
    })
    const readFinishedAt = performance.now()
    if (samples.length < limits.sampleTimings) {
      samples.push({ frameIndex, rafTime, readStartedAt, readFinishedAt })
    } else samplesDropped += 1
  }
  try {
    read(null)
    if (action === 'back') history.back()
    else if (action === 'forward') history.forward()
    else
      document
        .querySelector<HTMLAnchorElement>(
          `header a[aria-label="${action === 'posts' ? 'Posts' : 'Media'}"]`,
        )!
        .click()
    await new Promise<void>((resolve, reject) => {
      const tick = (rafTime: number): void => {
        try {
          read(rafTime)
          const destinationMounted =
            firstMountedPane !== undefined &&
            frames.at(-1)?.panes.some((pane) => pane.tab === firstMountedPane)
          if (!destinationMounted && performance.now() - began < duration)
            requestAnimationFrame(tick)
          else resolve()
        } catch (error: unknown) {
          reject(error)
        }
      }
      requestAnimationFrame(tick)
    })
  } finally {
    ended = performance.now()
    for (const { observer, buffer } of activeObservers) {
      collect(buffer, observer.takeRecords())
      observer.disconnect()
    }
  }

  const overlapsCapture = (entry: PerformanceEntry): boolean =>
    entry.startTime <= ended && entry.startTime + entry.duration >= began
  const entryTiming = (entry: PerformanceEntry): EntryTiming => ({
    name: entry.name,
    entryType: entry.entryType,
    startTime: entry.startTime,
    duration: entry.duration,
  })
  const scriptTiming = (entry: ScriptEntry): ScriptTiming => ({
    ...entryTiming(entry),
    executionStart: entry.executionStart ?? null,
    forcedStyleAndLayoutDuration: entry.forcedStyleAndLayoutDuration ?? null,
    pauseDuration: entry.pauseDuration ?? null,
    sourceURL: entry.sourceURL ?? null,
    sourceFunctionName: entry.sourceFunctionName ?? null,
    sourceCharPosition: entry.sourceCharPosition ?? null,
    invoker: entry.invoker ?? null,
    invokerType: entry.invokerType ?? null,
    windowAttribution: entry.windowAttribution ?? null,
  })
  const animationTiming = (entry: AnimationEntry): AnimationTiming => {
    const scripts = entry.scripts ?? []
    return {
      ...entryTiming(entry),
      renderStart: entry.renderStart ?? null,
      styleAndLayoutStart: entry.styleAndLayoutStart ?? null,
      blockingDuration: entry.blockingDuration ?? null,
      firstUIEventTimestamp: entry.firstUIEventTimestamp ?? null,
      scripts: scripts.slice(0, limits.scriptsPerAnimationFrame).map(scriptTiming),
      scriptsDropped: Math.max(0, scripts.length - limits.scriptsPerAnimationFrame),
    }
  }
  const longTasks: EntryTiming[] = []
  const longAnimationFrames: AnimationTiming[] = []
  for (const { buffer } of activeObservers) {
    for (const entry of buffer.entries) {
      if (!overlapsCapture(entry)) continue
      if (buffer.entryType === 'longtask') longTasks.push(entryTiming(entry))
      else longAnimationFrames.push(animationTiming(entry as AnimationEntry))
    }
  }
  const resources: ResourceTiming[] = []
  let resourcesDropped = 0
  // Resource timing contains completed requests still retained by the browser.
  for (const entry of performance.getEntriesByType('resource')) {
    if (!overlapsCapture(entry)) continue
    if (resources.length >= limits.resources) {
      resourcesDropped += 1
      continue
    }
    const resource = entry as PerformanceResourceTiming
    resources.push({
      ...entryTiming(resource),
      initiatorType: resource.initiatorType,
      responseEnd: resource.responseEnd,
      transferSize: resource.transferSize,
      encodedBodySize: resource.encodedBodySize,
      decodedBodySize: resource.decodedBodySize,
    })
  }
  return {
    frames,
    diagnostics: {
      timeOrigin: performance.timeOrigin,
      began,
      ended,
      observerAvailable,
      supportedEntryTypes,
      observedEntryTypes: activeObservers.map(({ buffer }) => buffer.entryType),
      observerErrors,
      limits,
      samples,
      samplesDropped,
      longTasks,
      longAnimationFrames,
      observerEntriesDropped: activeObservers.map(({ buffer }) => ({
        entryType: buffer.entryType,
        count: buffer.dropped,
      })),
      resources,
      resourcesDropped,
    },
  }
}
