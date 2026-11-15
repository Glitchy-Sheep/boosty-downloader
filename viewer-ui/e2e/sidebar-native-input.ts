import type { Page } from '@playwright/test'

import { pane } from './post-fixtures'

export type ReaderInput = 'wheel' | 'keyboard'
export type ReaderInputSnapshot = {
  trusted: boolean
  animating: boolean
  sidebarWidth: number
  scrollTop: number
  time: number
}
export type ReaderInputAttempt = {
  outcome: 'captured' | 'missed' | 'error'
  triggerAt: number | null
  transitionAt: number | null
  ready: { time: number; width: number } | null
  captured: ReaderInputSnapshot | null
  error: string | null
}

type ReaderInputProbe = { result: Promise<ReaderInputAttempt>; cancel: () => void }

declare global {
  interface Window {
    sidebarNativeReaderInput?: () => Promise<void>
    sidebarReaderProbe?: ReaderInputProbe
  }
}

const INPUT_CAPTURE_TIMEOUT_MS = 5_000

/** Dispatch native input at the first observed intermediate sidebar width. */
export async function captureReaderInput(
  page: Page,
  input: ReaderInput,
  expandedWidth: number,
): Promise<ReaderInputAttempt> {
  const binding = await page.exposeBinding('sidebarNativeReaderInput', async () => {
    if (input === 'wheel') await page.mouse.wheel(0, 350)
    else await page.keyboard.press('PageDown')
  })
  try {
    await pane(page).evaluate(
      (element, { input, expandedWidth, timeoutMs }) => {
        const panel = document.querySelector<HTMLElement>('#sidebar[data-panel]')
        const group = document.querySelector<HTMLElement>('[data-sidebar-layout]')
        if (!panel || !group) throw new Error('Missing sidebar glide geometry')
        let resolve!: (result: ReaderInputAttempt) => void
        const result = new Promise<ReaderInputAttempt>((accept) => {
          resolve = accept
        })
        let triggerAt: number | null = null
        let transitionAt: number | null = null
        let ready: ReaderInputAttempt['ready'] = null
        let captured: ReaderInputSnapshot | null = null
        let dispatchComplete = false
        let settled = false
        let frame: number | null = null
        let timeout: number | null = null
        const eventName = input === 'wheel' ? 'wheel' : 'keydown'
        const cleanup = (): void => {
          if (frame !== null) cancelAnimationFrame(frame)
          if (timeout !== null) window.clearTimeout(timeout)
          element.removeEventListener(eventName, capture, true)
          element.removeEventListener('keydown', trigger, true)
          panel.removeEventListener('transitionstart', transition)
        }
        const finish = (
          outcome: ReaderInputAttempt['outcome'],
          error: string | null = null,
        ): void => {
          if (settled) return
          settled = true
          cleanup()
          resolve({ outcome, triggerAt, transitionAt, ready, captured, error })
        }
        const capture = (event: Event): void => {
          if (!ready || captured) return
          if (event instanceof KeyboardEvent && event.key !== 'PageDown') return
          captured = {
            trusted: event.isTrusted,
            animating: group.hasAttribute('data-animating'),
            sidebarWidth: panel.getBoundingClientRect().width,
            scrollTop: element.scrollTop,
            time: performance.now(),
          }
          if (dispatchComplete) finish('captured')
        }
        const trigger = (event: Event): void => {
          if (event instanceof KeyboardEvent && event.code === 'BracketLeft' && triggerAt === null)
            triggerAt = performance.now()
        }
        const observe = (): void => {
          frame = null
          const sidebarWidth = panel.getBoundingClientRect().width
          const animating = group.hasAttribute('data-animating')
          if (!animating || sidebarWidth <= 0) {
            finish('missed')
            return
          }
          if (sidebarWidth >= expandedWidth) {
            frame = requestAnimationFrame(observe)
            return
          }
          ready = { time: performance.now(), width: sidebarWidth }
          const send = window.sidebarNativeReaderInput
          if (!send) {
            finish('error', 'The native input binding is unavailable.')
            return
          }
          void send().then(
            () => {
              dispatchComplete = true
              if (captured) finish('captured')
            },
            (error: unknown) => finish('error', String(error)),
          )
        }
        const transition = (event: TransitionEvent): void => {
          if (event.target !== panel || event.propertyName !== 'flex-grow') return
          panel.removeEventListener('transitionstart', transition)
          transitionAt = performance.now()
          frame = requestAnimationFrame(observe)
        }
        window.sidebarReaderProbe = {
          result,
          cancel: () => finish('error', 'The native input probe was cancelled.'),
        }
        element.addEventListener(eventName, capture, { capture: true, passive: true })
        element.addEventListener('keydown', trigger, { capture: true, passive: true })
        panel.addEventListener('transitionstart', transition)
        timeout = window.setTimeout(() => {
          if (ready) finish('error', 'Native input was not captured before the probe deadline.')
          else finish('missed')
        }, timeoutMs)
      },
      { input, expandedWidth, timeoutMs: INPUT_CAPTURE_TIMEOUT_MS },
    )
    await page.keyboard.press('[')
    return await page.evaluate(() => {
      if (!window.sidebarReaderProbe) throw new Error('The native input probe is unavailable.')
      return window.sidebarReaderProbe.result
    })
  } finally {
    try {
      await page.evaluate(() => {
        window.sidebarReaderProbe?.cancel()
        delete window.sidebarReaderProbe
      })
    } finally {
      await binding.dispose()
    }
  }
}
