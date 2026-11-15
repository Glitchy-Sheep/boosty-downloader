import { expect, openPost, POSTS, test } from './post-fixtures'
import { expectFullMobilePost, openMobileSidebar, sheet } from './mobile-sidebar-fixtures'
import { expectWidth, frames, savedPreference, seedPreference } from './sidebar-fixtures'
import { requireFixture } from './required-fixture'

type MobileExtentFrame = {
  viewport: number
  sidebar: number
  post: number
  group: number
  heightDifference: number
  leftDifference: number
}

declare global {
  interface Window {
    mobileExtentCapture?: { running: boolean; frames: MobileExtentFrame[] }
  }
}

for (const collapsed of [false, true]) {
  test(`mobile zero-width layout is preserved in every frame with saved collapsed=${collapsed}`, async ({
    page,
    corpus,
  }, info) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await seedPreference(page, JSON.stringify({ width: 500, collapsed }))
    await openPost(page, corpus, POSTS.reader)
    await expectFullMobilePost(page)
    await page.evaluate(() => {
      const capture = { running: true, frames: [] as MobileExtentFrame[] }
      window.mobileExtentCapture = capture
      const tick = (): void => {
        if (!capture.running) return
        const group = document.querySelector('[data-sidebar-layout]')?.getBoundingClientRect()
        const sidebar = document.querySelector('#sidebar[data-panel]')?.getBoundingClientRect()
        const post = document.querySelector('#post[data-panel]')?.getBoundingClientRect()
        if (group && sidebar && post)
          capture.frames.push({
            viewport: innerWidth,
            sidebar: sidebar.width,
            post: post.width,
            group: group.width,
            heightDifference: Math.abs(post.height - group.height),
            leftDifference: Math.abs(post.x - group.x),
          })
        requestAnimationFrame(tick)
      }
      tick()
    })
    let captured: MobileExtentFrame[] = []
    try {
      const hiddenEdge = page.locator('[role="separator"][aria-label="Sidebar width"]')
      await hiddenEdge.dispatchEvent('keydown', {
        key: 'ArrowRight',
        code: 'ArrowRight',
        bubbles: true,
      })
      await hiddenEdge.dispatchEvent('dblclick', { bubbles: true, clientX: 0, clientY: 300 })
      await page.mouse.move(1, 400)
      await page.mouse.down()
      await page.mouse.move(150, 400, { steps: 5 })
      await page.mouse.up()
      expect(await savedPreference(page)).toEqual({ width: 500, collapsed })
      for (const width of [360, 820, 767, 1440, 390]) {
        await page.setViewportSize({ width, height: 1000 })
        await frames(page, 4)
        if (width < 768) await expectFullMobilePost(page)
        else {
          const available = await page
            .locator('[data-sidebar-layout]')
            .evaluate((element) => element.getBoundingClientRect().width)
          const edge = await page
            .locator('[role="separator"][aria-label="Sidebar width"]')
            .evaluate((element) => element.getBoundingClientRect().width)
          await expectWidth(page, collapsed ? 0 : Math.min(500, available - edge - 400))
        }
        expect(await savedPreference(page)).toEqual({ width: 500, collapsed })
      }
    } finally {
      captured = await page.evaluate(() => {
        const capture = window.mobileExtentCapture
        if (!capture) throw new Error('Missing mobile extent recorder')
        capture.running = false
        delete window.mobileExtentCapture
        return capture.frames
      })
      await info.attach('mobile-panel-extents.json', {
        body: JSON.stringify(captured),
        contentType: 'application/json',
      })
    }
    const mobile = captured.filter((frame) => frame.viewport < 768)
    expect(mobile.length).toBeGreaterThan(12)
    expect(new Set(mobile.map((frame) => frame.viewport))).toEqual(new Set([390, 360, 767]))
    expect(
      Math.max(
        ...mobile.map((frame) =>
          Math.max(
            frame.sidebar,
            Math.abs(frame.post - frame.group),
            frame.heightDifference,
            frame.leftDifference,
          ),
        ),
      ),
    ).toBeLessThanOrEqual(0.5)
  })
}

test.describe('native sheet touch scrolling', () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } })
  test('a native Chromium swipe scrolls the timeline inside the modal sheet', async ({
    page,
    corpus,
    browserName,
  }) => {
    test.skip(
      browserName !== 'chromium',
      'Public Playwright touch-move injection is available through Chromium CDP only',
    )
    await openPost(page, corpus, POSTS.reader)
    await openMobileSidebar(page)
    const list = sheet(page).locator('[data-post-list]')
    await list.evaluate((element) => {
      element.scrollTop = 0
    })
    const box = requireFixture(await list.boundingBox())
    const x = box.x + box.width / 2
    const y = box.y + box.height * 0.8
    const session = await page.context().newCDPSession(page)
    try {
      await session.send('Input.dispatchTouchEvent', {
        type: 'touchStart',
        touchPoints: [{ x, y }],
      })
      for (let step = 1; step <= 8; step++) {
        await session.send('Input.dispatchTouchEvent', {
          type: 'touchMove',
          touchPoints: [{ x, y: y - step * box.height * 0.06 }],
        })
        await frames(page)
      }
      await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
      await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBeGreaterThan(40)
      await expect(sheet(page)).toBeVisible()
    } finally {
      await session.detach()
    }
  })
})
