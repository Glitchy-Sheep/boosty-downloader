import { expect, origin, test } from './fixtures'
import { closeMobileSidebar, openMobileSidebar, sheet, timeline } from './mobile-sidebar-fixtures'
import { frames } from './sidebar-fixtures'
import { expectSelected, installTimeline, largeRows, postPath } from './timeline-fixtures'
import { requireFixture } from './required-fixture'

type TimelineFrame = {
  phase: string
  id: string | null
  offset: number | null
  width: number
  height: number
  scroll: number
}

declare global {
  interface Window {
    mobileTimelineCapture?: { running: boolean; phase: string; frames: TimelineFrame[] }
  }
}

for (const position of ['middle', 'end'] as const) {
  for (const snippets of [false, true]) {
    test(`${position} anchor with search=${snippets} survives sheet remount and docking in every frame`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width: 390, height: 844 })
      const posts = largeRows(3000).map((post) => ({
        ...post,
        ...(snippets
          ? {
              match: {
                title: [{ text: post.title, matched: false }],
                text: [
                  { text: 'A long search excerpt containing ', matched: false },
                  { text: 'needle', matched: true },
                  {
                    text: ' and enough context to wrap within a narrow timeline row.',
                    matched: false,
                  },
                ],
              },
            }
          : {}),
      }))
      await installTimeline(page, posts)
      const selected = requireFixture(posts[0])
      await page.goto(`${origin()}${postPath(selected.id, snippets ? 'q=needle' : '')}`)
      await expectSelected(page, selected)
      await openMobileSidebar(page)
      const list = timeline(page).locator('[data-post-list]')
      await expect(list.locator('[data-post-id]').first()).toBeVisible()
      await list.evaluate((element, position) => {
        element.scrollTop =
          (element.scrollHeight - element.clientHeight) * (position === 'end' ? 1 : 0.5)
      }, position)
      await frames(page, 4)
      await page.evaluate(() => {
        const capture = { running: true, phase: 'baseline', frames: [] as TimelineFrame[] }
        window.mobileTimelineCapture = capture
        const tick = (): void => {
          if (!capture.running) return
          const list = document.querySelector('[data-post-list]')
          if (list) {
            const box = list.getBoundingClientRect()
            const inset = list.querySelector('[data-month]')?.getBoundingClientRect().height ?? 0
            const top = box.top + inset
            const row = [...list.querySelectorAll<HTMLElement>('[data-post-id]')]
              .map((element) => ({ element, box: element.getBoundingClientRect() }))
              .filter(({ box }) => box.bottom > top + 1)
              .sort((a, b) => a.box.top - b.box.top)[0]
            if (box.width > 0 && box.height > 0)
              capture.frames.push({
                phase: capture.phase,
                id: row?.element.dataset.postId ?? null,
                offset: row ? row.box.top - top : null,
                width: box.width,
                height: box.height,
                scroll: list.scrollTop,
              })
          }
          requestAnimationFrame(tick)
        }
        tick()
      })
      const baseline = requireFixture(
        await page.evaluate(() => window.mobileTimelineCapture?.frames[0]),
      )
      expect(baseline.id).not.toBeNull()
      let captured: TimelineFrame[] = []
      try {
        await closeMobileSidebar(page)
        await page.evaluate(() => {
          if (window.mobileTimelineCapture) window.mobileTimelineCapture.phase = 'reopen'
        })
        await openMobileSidebar(page)
        await frames(page, 4)
        for (const viewport of [
          { width: 360, height: 740 },
          { width: 820, height: 1180 },
          { width: 390, height: 844 },
        ]) {
          await page.evaluate((width) => {
            if (window.mobileTimelineCapture) window.mobileTimelineCapture.phase = `width-${width}`
          }, viewport.width)
          await page.setViewportSize(viewport)
          if (viewport.width === 390) await openMobileSidebar(page)
          if (viewport.width === 820) await expect(sheet(page)).toHaveCount(0)
          await frames(page, 4)
          await expect(list.locator('[data-post-id]').first()).toBeAttached()
        }
      } finally {
        captured = await page.evaluate(() => {
          const capture = window.mobileTimelineCapture
          if (!capture) throw new Error('Missing mobile timeline recorder')
          capture.running = false
          delete window.mobileTimelineCapture
          return capture.frames
        })
        await info.attach('mobile-timeline-frames.json', {
          body: JSON.stringify({ baseline, captured }),
          contentType: 'application/json',
        })
      }
      expect(captured.length).toBeGreaterThan(12)
      expect(new Set(captured.map((frame) => frame.phase))).toEqual(
        new Set(['baseline', 'reopen', 'width-360', 'width-820', 'width-390']),
      )
      expect(captured.every((frame) => frame.id !== null && frame.id === baseline.id)).toBe(true)
      expect(
        Math.max(
          ...captured.map((frame) =>
            Math.abs(requireFixture(frame.offset) - requireFixture(baseline.offset)),
          ),
        ),
      ).toBeLessThanOrEqual(1)
      expect(new URL(page.url()).pathname).toBe(postPath(selected.id))
      expect(new URL(page.url()).searchParams.get('q')).toBe(snippets ? 'needle' : null)
    })
  }
}
