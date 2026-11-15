import { expect, API_PATH, AUTHOR, openPost, pane, POSTS, readyPlayer, test } from './post-fixtures'
import { expectFullMobilePost, sheet } from './mobile-sidebar-fixtures'
import { requireFixture } from './required-fixture'
import {
  blurControl,
  content,
  expectWidth,
  frames,
  layout,
  physicalBracket,
  savedPreference,
  seedPreference,
  separator,
  toggle,
} from './sidebar-fixtures'

const READER_RESIZE_PAUSE_MS = 400

for (const sequence of ['rapid', 'paused'] as const) {
  for (const collapsed of [false, true]) {
    test(`${sequence} crossing 768px keeps post DOM, scroll and playback with collapsed=${collapsed}`, async ({
      page,
      corpus,
    }) => {
      await seedPreference(page, JSON.stringify({ width: 500, collapsed }))
      await openPost(page, corpus, POSTS.reader)
      await expectWidth(page, collapsed ? 0 : 500)
      const article = await pane(page).locator('article').elementHandle()
      const section = await pane(page).elementHandle()
      const audio = pane(page).locator('audio').first()
      const player = await audio.elementHandle()
      await readyPlayer(audio)
      await audio.evaluate(async (element: HTMLMediaElement) => {
        element.muted = true
        element.currentTime = 2
        await element.play()
      })
      await pane(page).evaluate((element) => {
        element.scrollTop = 120
      })
      const scroll = await pane(page).evaluate((element) => element.scrollTop)
      expect(scroll).toBe(120)
      for (const width of [768, 767, 390, 820, 1440]) {
        if (sequence === 'paused') {
          await page.waitForTimeout(READER_RESIZE_PAUSE_MS)
          expect(await pane(page).evaluate((element) => element.scrollTop)).toBe(scroll)
        }
        await page.setViewportSize({ width, height: 1000 })
        await expect(layout(page)).toHaveAttribute(
          'data-sidebar-layout',
          width < 768 ? 'mobile' : 'docked',
        )
        await frames(page, 3)
        expect(
          await requireFixture(section).evaluate(
            (element) => element === document.querySelector('[aria-label="Selected post"]'),
          ),
        ).toBe(true)
        expect(
          await requireFixture(article).evaluate(
            (element) => element === document.querySelector('[aria-label="Selected post"] article'),
          ),
        ).toBe(true)
        expect(
          await requireFixture(player).evaluate(
            (element) => element === document.querySelector('[aria-label="Selected post"] audio'),
          ),
        ).toBe(true)
        expect(await pane(page).evaluate((element) => element.scrollTop)).toBe(scroll)
        expect(
          await audio.evaluate(
            (element: HTMLMediaElement) => !element.paused && element.currentTime >= 2,
          ),
        ).toBe(true)
        expect(await savedPreference(page)).toEqual({ width: 500, collapsed })
        if (width < 768) {
          await expect(toggle(page)).toBeEnabled()
          await expect(toggle(page)).toHaveAccessibleName('Show sidebar')
          await expect(toggle(page)).toHaveAttribute('aria-expanded', 'false')
          await expect(separator(page)).toHaveCount(0)
          await expectFullMobilePost(page)
          await expect(sheet(page)).toHaveCount(0)
          await expect(content(page)).toHaveCount(0)
        }
      }
      await expectWidth(page, collapsed ? 0 : 500)
      await audio.evaluate((element: HTMLMediaElement) => element.pause())
    })
  }
}

test('Media retains the header reservation and cannot resize hidden Posts', async ({
  page,
  corpus,
}) => {
  await seedPreference(page, JSON.stringify({ width: 500, collapsed: false }))
  await openPost(page, corpus, POSTS.reader)
  const logo = page.getByRole('link', { name: 'Boosty Library', exact: true })
  const posts = page
    .getByRole('navigation', { name: 'Author', exact: true })
    .getByRole('link', { name: 'Posts', exact: true })
  const logoBox = await logo.boundingBox()
  const tabBox = await posts.boundingBox()
  await page
    .getByRole('navigation', { name: 'Author', exact: true })
    .getByRole('link', { name: 'Media', exact: true })
    .click()
  await expect(page.getByRole('region', { name: 'Author media' })).toBeVisible()
  await expect(toggle(page)).toBeDisabled()
  await expect(toggle(page)).toBeHidden()
  expect(await logo.boundingBox()).toEqual(logoBox)
  expect(await posts.boundingBox()).toEqual(tabBox)
  await blurControl(page)
  await physicalBracket(page)
  await page.keyboard.press('/')
  await page.locator('[role="separator"][aria-label="Sidebar width"]').evaluate((element) => {
    const box = element.getBoundingClientRect()
    element.dispatchEvent(
      new MouseEvent('dblclick', { bubbles: true, clientX: box.x, clientY: box.y }),
    )
  })
  expect(await savedPreference(page)).toEqual({ width: 500, collapsed: false })
  expect(await content(page).evaluate((element) => element.contains(document.activeElement))).toBe(
    false,
  )
  await posts.click()
  await expectWidth(page, 500)
})

test('loading, errors and direct Media keep one fixed header slot', async ({ page, corpus }) => {
  let release: (() => void) | undefined
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`**${API_PATH}`, async (route) => {
    await held
    await route.fulfill({
      status: 503,
      json: { error: { code: 'unavailable', message: 'Temporarily unavailable' } },
    })
  })
  await page.goto(`${corpus.origin}/a/${AUTHOR}`)
  const logo = page.getByRole('link', { name: 'Boosty Library', exact: true })
  const startSlot = page.locator('[data-header-slot="start"]')
  await expect(startSlot).toHaveCount(1)
  await expect(toggle(page)).toHaveCount(0)
  const logoBox = await logo.boundingBox()
  const slot = await startSlot.evaluate((element) => {
    const box = element.getBoundingClientRect()
    return { x: box.x, width: box.width }
  })
  expect(slot.width).toBe(28)
  requireFixture(release)()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(toggle(page)).toHaveCount(0)
  expect(await logo.boundingBox()).toEqual(logoBox)
  expect(
    await startSlot.evaluate((element) => {
      const box = element.getBoundingClientRect()
      return { x: box.x, width: box.width }
    }),
  ).toEqual(slot)
  await page.unroute(`**${API_PATH}`)
  await page.goto(`${corpus.origin}/a/${AUTHOR}/media?view=images`)
  await expect(page.getByRole('region', { name: 'Author media' })).toBeVisible()
  await expect(toggle(page)).toHaveCount(1)
  await expect(toggle(page)).toBeDisabled()
  await expect(toggle(page)).toBeHidden()
  expect(await logo.boundingBox()).toEqual(logoBox)
  expect(
    await startSlot.evaluate((element) => {
      const box = element.getBoundingClientRect()
      return { x: box.x, width: box.width }
    }),
  ).toEqual(slot)
})

test.describe('full-page mobile reader', () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } })

  test('vertical content can scroll and every disabled panel permits native touch panning', async ({
    page,
    corpus,
  }) => {
    await openPost(page, corpus, POSTS.reader)
    await expect(layout(page)).toHaveAttribute('data-sidebar-layout', 'mobile')
    await expectFullMobilePost(page)
    const ancestors = await pane(page).evaluate((element: HTMLElement) => {
      const touch: string[] = []
      for (let current: HTMLElement | null = element; current; current = current.parentElement) {
        touch.push(getComputedStyle(current).touchAction)
        if (current.hasAttribute('data-sidebar-layout')) break
      }
      return touch
    })
    expect(ancestors.every((value) => value !== 'pan-x' && value !== 'none')).toBe(true)
    await pane(page).hover()
    await page.mouse.wheel(0, 350)
    await expect.poll(() => pane(page).evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  })

  test('a native Chromium touch swipe scrolls the selected post inside the full-page mobile layout', async ({
    page,
    corpus,
    browserName,
  }) => {
    test.skip(
      browserName !== 'chromium',
      'Public Playwright touch-move injection is available through Chromium CDP only',
    )
    await openPost(page, corpus, POSTS.reader)
    const box = requireFixture(await pane(page).boundingBox())
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
      await expect
        .poll(() => pane(page).evaluate((element) => element.scrollTop))
        .toBeGreaterThan(40)
    } finally {
      await session.detach()
    }
  })
})
