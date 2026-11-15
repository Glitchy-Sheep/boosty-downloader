import type { Page } from '@playwright/test'

import { expect } from './media-fixtures'

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

/** Record rendered frames, including the delayed response and the first mounted pane. */
export async function switchFrames(
  page: Page,
  action: TabAction,
  duration = 550,
): Promise<SwitchFrame[]> {
  return page.evaluate(
    async ({ action, duration }) => {
      const frames: SwitchFrame[] = []
      const began = performance.now()
      const read = (): void => {
        const article = document.querySelector('.author-pane[data-tab="posts"] article')
        frames.push({
          time: performance.now() - began,
          logo: document.querySelector('a[aria-label="Boosty Library"]')!.getBoundingClientRect()
            .left,
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
      }
      read()
      if (action === 'back') history.back()
      else if (action === 'forward') history.forward()
      else
        document
          .querySelector<HTMLAnchorElement>(
            `header a[aria-label="${action === 'posts' ? 'Posts' : 'Media'}"]`,
          )!
          .click()
      await new Promise<void>((resolve) => {
        const tick = (): void => {
          read()
          if (performance.now() - began < duration) requestAnimationFrame(tick)
          else resolve()
        }
        requestAnimationFrame(tick)
      })
      return frames
    },
    { action, duration },
  )
}

export function verifySwitch(frames: SwitchFrame[], destination: TabName): void {
  const coverage = frames.map(
    (frame) =>
      1 -
      frame.panes
        .filter((pane) => pane.visible)
        .reduce((rest, pane) => rest * (1 - pane.opacity), 1),
  )
  expect(
    Math.min(...coverage),
    'Every rendered frame keeps at least 99% pane coverage',
  ).toBeGreaterThanOrEqual(0.99)
  expect(new Set(frames.map((frame) => Math.round(frame.logo * 10))).size).toBe(1)
  expect(new Set(frames.map((frame) => Math.round(frame.pill))).size).toBeGreaterThanOrEqual(4)
  const incoming = frames.flatMap((frame) => {
    const pane = frame.panes.find((value) => value.tab === destination)
    return pane ? [{ ...pane, time: frame.time }] : []
  })
  const moving = incoming.filter((pane) => pane.visible && Math.abs(pane.x) > 0.5)
  expect(new Set(moving.map((pane) => Math.round(pane.x))).size).toBeGreaterThanOrEqual(3)
  expect(moving.every((pane) => (destination === 'media' ? pane.x > 0 : pane.x < 0))).toBe(true)
  const appeared = incoming.find((pane) => pane.visible)
  const settled = incoming.find(
    (pane) => pane.visible && pane.opacity === 1 && Math.abs(pane.x) < 0.1,
  )
  expect(appeared).toBeDefined()
  expect(settled).toBeDefined()
  expect(settled!.time - appeared!.time).toBeLessThan(400)
  const last = frames.at(-1)!
  expect(last.panes.find((pane) => pane.tab === destination)).toMatchObject({
    opacity: 1,
    visible: true,
    inert: false,
  })
  expect(
    last.panes
      .filter((pane) => pane.tab !== destination)
      .every((pane) => !pane.visible && pane.inert),
  ).toBe(true)
}

export async function firstTile(page: Page): Promise<string> {
  await page.waitForFunction(
    () => {
      const scroller = document.querySelector('[data-media-scroller]')
      if (!scroller) return false
      const viewport = scroller.getBoundingClientRect()
      return [...scroller.querySelectorAll('button[data-media-id]')].some((tile) => {
        const bounds = tile.getBoundingClientRect()
        return bounds.bottom > viewport.top + 1 && bounds.top < viewport.bottom
      })
    },
    undefined,
    { timeout: 5_000 },
  )
  return page.locator('[data-media-scroller]').evaluate((scroller) => {
    const top = scroller.getBoundingClientRect().top
    const first = [...scroller.querySelectorAll<HTMLButtonElement>('button[data-media-id]')]
      .filter((tile) => tile.getBoundingClientRect().bottom > top + 1)
      .sort(
        (left, right) =>
          left.getBoundingClientRect().top - right.getBoundingClientRect().top ||
          left.getBoundingClientRect().left - right.getBoundingClientRect().left,
      )[0]
    if (!first?.dataset.mediaId) throw new Error('No visible media tile')
    return first.dataset.mediaId
  })
}

export async function anchored(page: Page, id: string): Promise<boolean> {
  return page.locator('[data-media-scroller]').evaluate((scroller, id) => {
    const top = scroller.getBoundingClientRect().top
    const tile = [...scroller.querySelectorAll<HTMLElement>('[data-media-id]')].find(
      (item) => item.dataset.mediaId === id,
    )
    const bounds = tile?.getBoundingClientRect()
    return Boolean(bounds && bounds.bottom > top + 1 && bounds.top <= top + 1)
  }, id)
}

export type AnchorFrame = {
  time: number
  width: number
  gridWidth: number
  anchored: boolean
  scroll: number
  scrollerTop: number
  tileTop: number | null
  tileBottom: number | null
  rowTransform: string | null
  columns: string | null
}
declare global {
  interface Window {
    mediaAnchorCapture?: { running: boolean; frames: AnchorFrame[] }
  }
}

export async function beginAnchorFrames(page: Page, id: string): Promise<void> {
  await page.evaluate((id) => {
    const capture = { running: true, frames: [] as AnchorFrame[] }
    const began = performance.now()
    window.mediaAnchorCapture = capture
    const tick = (): void => {
      if (!capture.running) return
      const scroller = document.querySelector<HTMLElement>('[data-media-scroller]')!
      const top = scroller.getBoundingClientRect().top
      const tile = [...scroller.querySelectorAll<HTMLElement>('[data-media-id]')].find(
        (element) => element.dataset.mediaId === id,
      )
      const bounds = tile?.getBoundingClientRect()
      const row = tile?.closest('[data-media-grid] > *')
      capture.frames.push({
        time: performance.now() - began,
        width: innerWidth,
        gridWidth: document.querySelector('[data-media-grid]')!.getBoundingClientRect().width,
        scroll: scroller.scrollTop,
        scrollerTop: top,
        tileTop: bounds?.top ?? null,
        tileBottom: bounds?.bottom ?? null,
        rowTransform: row ? getComputedStyle(row).transform : null,
        columns: row ? getComputedStyle(row).gridTemplateColumns : null,
        anchored: Boolean(bounds && bounds.top <= top + 1 && bounds.bottom > top + 1),
      })
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }, id)
}

export async function endAnchorFrames(page: Page): Promise<AnchorFrame[]> {
  return page.evaluate(() => {
    const capture = window.mediaAnchorCapture
    if (!capture) throw new Error('Anchor recording was not started')
    capture.running = false
    delete window.mediaAnchorCapture
    return capture.frames
  })
}
