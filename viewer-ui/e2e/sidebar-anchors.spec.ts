import type { Page } from '@playwright/test'

import { expect, origin, test } from './fixtures'
import { requireFixture } from './required-fixture'
import { expectWidth, frames, seedPreference, separator, toggle } from './sidebar-fixtures'
import { expectSelected, installTimeline, largeRows, postPath, sidebar } from './timeline-fixtures'

type AnchorFrame = {
  time: number
  width: number
  id: string | null
  offset: number | null
  rowHeight: number | null
  listTop: number
  clientHeight: number
  scrollHeight: number
  scrollTop: number
  headerHeight: number
  rowTop: number | null
  rowBottom: number | null
}

declare global {
  interface Window {
    sidebarAnchorCapture?: { running: boolean; frames: AnchorFrame[] }
  }
}

async function beginCapture(page: Page): Promise<void> {
  await page.evaluate(() => {
    const list = document.querySelector('[data-post-list]')
    const panel = document.querySelector('#sidebar[data-panel]')
    if (!list || !panel) throw new Error('Missing sidebar geometry')
    const capture = { running: true, frames: [] as AnchorFrame[] }
    window.sidebarAnchorCapture = capture
    const began = performance.now()
    const tick = (): void => {
      if (!capture.running) return
      const listTop = list.getBoundingClientRect().top
      const headerHeight = list.querySelector('[data-month]')?.getBoundingClientRect().height ?? 0
      const top = listTop + headerHeight
      const visible = [...list.querySelectorAll<HTMLElement>('[data-post-id]')]
        .map((element) => ({ element, bounds: element.getBoundingClientRect() }))
        .filter(({ bounds }) => bounds.bottom > top + 1)
        .sort((a, b) => a.bounds.top - b.bounds.top)[0]
      capture.frames.push({
        time: performance.now() - began,
        width: panel.getBoundingClientRect().width,
        id: visible?.element.dataset.postId ?? null,
        offset: visible ? visible.bounds.top - top : null,
        rowHeight: visible?.bounds.height ?? null,
        listTop,
        clientHeight: list.clientHeight,
        scrollHeight: list.scrollHeight,
        scrollTop: list.scrollTop,
        headerHeight,
        rowTop: visible?.bounds.top ?? null,
        rowBottom: visible?.bounds.bottom ?? null,
      })
      requestAnimationFrame(tick)
    }
    tick()
  })
}

async function snapshot(page: Page): Promise<AnchorFrame> {
  return requireFixture(await page.evaluate(() => window.sidebarAnchorCapture?.frames.at(-1)))
}

async function endCapture(page: Page): Promise<AnchorFrame[]> {
  return page.evaluate(() => {
    const capture = window.sidebarAnchorCapture
    if (!capture) throw new Error('No sidebar frame recorder')
    capture.running = false
    delete window.sidebarAnchorCapture
    return capture.frames
  })
}

for (const position of ['middle', 'end'] as const) {
  for (const snippets of [false, true]) {
    test(`${position} anchors stay fixed in every drag frame with snippets=${snippets}`, async ({
      page,
    }, info) => {
      await seedPreference(page, JSON.stringify({ width: 260, collapsed: false }))
      const posts = largeRows(3000).map((post) => ({
        ...post,
        ...(snippets
          ? {
              match: {
                title: [{ text: post.title, matched: false }],
                text: [
                  { text: 'A long search excerpt with ', matched: false },
                  { text: 'needle', matched: true },
                  {
                    text: ' and enough surrounding text to wrap within a narrow timeline row.',
                    matched: false,
                  },
                ],
              },
            }
          : {}),
      }))
      await installTimeline(page, posts)
      const first = requireFixture(posts[0])
      await page.goto(`${origin()}${postPath(first.id, snippets ? 'q=needle' : '')}`)
      await expectSelected(page, first)
      await expectWidth(page, 260)
      const list = sidebar(page).locator('[data-post-list]')
      await list.evaluate((element, position) => {
        const maximum = element.scrollHeight - element.clientHeight
        element.scrollTop = position === 'end' ? maximum : maximum / 2
      }, position)
      await frames(page, 4)
      await expect(sidebar(page).locator('[data-post-id]').first()).toBeAttached()
      await beginCapture(page)
      const baseline = await snapshot(page)
      expect(baseline.id).not.toBeNull()
      const edge = requireFixture(await separator(page).boundingBox())
      const x = edge.x + edge.width / 2
      const y = edge.y + Math.min(100, edge.height / 2)
      const steps: AnchorFrame[] = [baseline]
      let captured: AnchorFrame[] = []
      await page.mouse.move(x, y)
      await page.mouse.down()
      try {
        const targets = [
          ...Array.from({ length: 38 }, (_, index) => 270 + index * 10),
          ...Array.from({ length: 38 }, (_, index) => 630 - index * 10),
        ]
        for (const target of targets) {
          await page.mouse.move(x + target - 260, y)
          await frames(page)
          const current = await snapshot(page)
          expect(Math.abs(current.width - target)).toBeLessThanOrEqual(0.5)
          const previous = requireFixture(steps.at(-1))
          expect(
            Math.abs(requireFixture(current.rowHeight) - requireFixture(previous.rowHeight)),
          ).toBeLessThanOrEqual(2)
          steps.push(current)
        }
      } finally {
        await page.mouse.up()
        await frames(page, 3)
        captured = await endCapture(page)
        await info.attach('sidebar-anchor-frames.json', {
          body: JSON.stringify({ baseline, steps, captured }),
          contentType: 'application/json',
        })
      }
      expect(captured.length).toBeGreaterThan(30)
      expect(new Set(captured.map((frame) => Math.round(frame.width))).size).toBeGreaterThan(20)
      expect(captured.every((frame) => frame.id === baseline.id)).toBe(true)
      expect(
        Math.max(
          ...captured.map((frame) =>
            Math.abs(requireFixture(frame.offset) - requireFixture(baseline.offset)),
          ),
        ),
      ).toBeLessThanOrEqual(1)
      await expectWidth(page, 260)
    })
  }
}

test('collapse clips the narrow timeline without changing its row anchor', async ({
  page,
}, info) => {
  await seedPreference(page, JSON.stringify({ width: 260, collapsed: false }))
  const posts = largeRows(3000)
  await installTimeline(page, posts)
  const first = requireFixture(posts[0])
  await page.goto(`${origin()}${postPath(first.id)}`)
  await expectSelected(page, first)
  await expectWidth(page, 260)
  await sidebar(page)
    .locator('[data-post-list]')
    .evaluate((element) => {
      element.scrollTop = (element.scrollHeight - element.clientHeight) / 2
    })
  await frames(page, 4)
  await beginCapture(page)
  const baseline = await snapshot(page)
  let captured: AnchorFrame[] = []
  try {
    for (const width of [0, 260]) {
      await toggle(page).click()
      await expectWidth(page, width)
    }
    await frames(page, 3)
  } finally {
    captured = await endCapture(page)
    await info.attach('sidebar-collapse-anchor-frames.json', {
      body: JSON.stringify({ baseline, captured }),
      contentType: 'application/json',
    })
  }
  expect(baseline.id).not.toBeNull()
  expect(captured.some((frame) => frame.width <= 0.5)).toBe(true)
  const reopened = requireFixture(captured.at(-1))
  expect(Math.abs(reopened.width - 260)).toBeLessThanOrEqual(0.5)
  expect(reopened.clientHeight).toBeGreaterThan(0)
  expect(reopened.id).toBe(baseline.id)
  expect(
    Math.abs(requireFixture(reopened.offset) - requireFixture(baseline.offset)),
  ).toBeLessThanOrEqual(1)
  const visible = captured.filter((frame) => frame.width > 0.5)
  expect(visible.length).toBeGreaterThan(1)
  expect(visible.every((frame) => frame.clientHeight > 0)).toBe(true)
  expect(visible.every((frame) => frame.id === baseline.id)).toBe(true)
  expect(
    visible.every(
      (frame) => Math.abs(requireFixture(frame.offset) - requireFixture(baseline.offset)) <= 1,
    ),
  ).toBe(true)
})
