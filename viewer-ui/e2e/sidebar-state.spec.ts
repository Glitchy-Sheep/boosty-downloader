import { openPost, pane, POSTS, expect, test } from './post-fixtures'
import {
  content,
  dragTo,
  expectWidth,
  layout,
  panel,
  savedPreference,
  seedPreference,
  separator,
  toggle,
  width,
  WIDTH,
} from './sidebar-fixtures'

for (const value of [
  '{broken',
  'null',
  '[]',
  '{"width":"500","collapsed":false}',
  '{"width":400,"collapsed":1}',
]) {
  test(`invalid preference ${value} leaves a usable default sidebar`, async ({ page, corpus }) => {
    await seedPreference(page, value)
    await openPost(page, corpus, POSTS.reader)
    await expectWidth(page, WIDTH.default)
    await expect(toggle(page)).toHaveAttribute('aria-expanded', 'true')
    await expect(content(page)).not.toHaveAttribute('inert')
    await dragTo(page, 450)
    expect(await savedPreference(page)).toEqual({ width: 450, collapsed: false })
  })
}

for (const preference of [
  { width: 100, expected: 260 },
  { width: 900, expected: 640 },
]) {
  test(`saved width ${preference.width} clamps to ${preference.expected}px`, async ({
    page,
    corpus,
  }) => {
    await seedPreference(page, JSON.stringify({ width: preference.width, collapsed: false }))
    await openPost(page, corpus, POSTS.reader)
    await expectWidth(page, preference.expected)
  })
}

test('blocked layout storage preserves resize, collapse and expansion', async ({
  page,
  corpus,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', {
      get() {
        throw new DOMException('Storage blocked', 'SecurityError')
      },
    })
  })
  await openPost(page, corpus, POSTS.reader)
  await expectWidth(page, WIDTH.default)
  await dragTo(page, 470)
  await toggle(page).click()
  await expectWidth(page, 0)
  await toggle(page).click()
  await expectWidth(page, 470)
  await page.reload()
  await expectWidth(page, WIDTH.default)
})

test('temporary viewport compression preserves the chosen width and a 400px post', async ({
  page,
  corpus,
}) => {
  await seedPreference(page, JSON.stringify({ width: 640, collapsed: false }))
  await openPost(page, corpus, POSTS.reader)
  await expectWidth(page, WIDTH.max)
  for (const viewport of [900, 820, 768]) {
    await page.setViewportSize({ width: viewport, height: 1000 })
    const available = await layout(page).evaluate(
      (element) => element.getBoundingClientRect().width,
    )
    const edge = await separator(page).evaluate((element) => element.getBoundingClientRect().width)
    await expectWidth(page, available - edge - 400)
    expect(
      await pane(page).evaluate((element) => element.getBoundingClientRect().width),
    ).toBeGreaterThanOrEqual(399.99)
    expect(await savedPreference(page)).toEqual({ width: 640, collapsed: false })
  }
  await page.reload()
  await expect.poll(() => width(page)).toBeLessThan(640)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await expectWidth(page, 640)
  expect(await savedPreference(page)).toEqual({ width: 640, collapsed: false })
})

test('collapsed reload and Enter preserve the chosen expansion width', async ({ page, corpus }) => {
  await seedPreference(page, JSON.stringify({ width: 500, collapsed: true }))
  await openPost(page, corpus, POSTS.reader)
  await expectWidth(page, 0)
  await expect(content(page)).toHaveAttribute('inert', '')
  await expect(toggle(page)).toHaveAccessibleName('Show sidebar')
  await separator(page).focus()
  await page.keyboard.press('Enter')
  await expectWidth(page, 500)
  expect(await savedPreference(page)).toEqual({ width: 500, collapsed: false })
  await page.keyboard.press('Enter')
  await expectWidth(page, 0)
  await page.reload()
  await expectWidth(page, 0)
  await expect(panel(page)).toBeAttached()
  await toggle(page).click()
  await expectWidth(page, 500)
})

test('Enter after widening a collapsed viewport restores chosen pixels', async ({
  page,
  corpus,
}) => {
  await page.setViewportSize({ width: 1000, height: 1000 })
  await openPost(page, corpus, POSTS.reader)
  await dragTo(page, 500)
  await toggle(page).click()
  await expectWidth(page, 0)
  await page.setViewportSize({ width: 1400, height: 1000 })
  await separator(page).focus()
  await page.keyboard.press('Enter')
  await expectWidth(page, 500)
  expect(await savedPreference(page)).toEqual({ width: 500, collapsed: false })
})
