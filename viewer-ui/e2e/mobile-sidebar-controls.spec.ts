import { expect, openPost, pane, POSTS, readyPlayer, test } from './post-fixtures'
import {
  closeMobileSidebar,
  expectFullMobilePost,
  openMobileSidebar,
  postElement,
  sheet,
  timeline,
} from './mobile-sidebar-fixtures'
import {
  blurControl,
  frames,
  physicalBracket,
  savedPreference,
  seedPreference,
  toggle,
} from './sidebar-fixtures'
import { requireFixture } from './required-fixture'

test.use({ viewport: { width: 390, height: 844 } })

test('sheet focus, shortcuts and nested Escape belong to the current modal layer', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader)
  await expectFullMobilePost(page)
  await openMobileSidebar(page)
  await expect(sheet(page)).toBeFocused()
  const input = sheet(page).getByRole('textbox', { name: 'Search posts' })
  await expect(input).not.toBeFocused()
  for (let index = 0; index < 22; index++) {
    await page.keyboard.press('Tab')
    expect(await sheet(page).evaluate((element) => element.contains(document.activeElement))).toBe(
      true,
    )
  }
  await closeMobileSidebar(page)
  await expect(toggle(page)).toBeFocused()
  await physicalBracket(page)
  await expect(sheet(page)).toBeFocused()
  await physicalBracket(page)
  await expect(sheet(page)).toHaveCount(0)
  await blurControl(page)
  await page.keyboard.press('/')
  await expect(input).toBeFocused()
  await input.fill('unsent search')
  await physicalBracket(page)
  await expect(input).toHaveValue('unsent search')
  await page.keyboard.press('Escape')
  await expect(input).toHaveValue('')
  await expect(input).toBeFocused()
  await expect(sheet(page)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(input).not.toBeFocused()
  await expect(sheet(page)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toHaveCount(0)
  await openMobileSidebar(page)
  const mark = sheet(page).getByRole('button', { name: 'Mark posts', exact: true })
  await mark.click()
  await physicalBracket(page)
  await page.keyboard.press('/')
  await expect(page.getByRole('menu')).toBeVisible()
  await expect(
    page.locator('#author-post-sidebar input[aria-label="Search posts"]'),
  ).not.toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
  await expect(mark).toBeFocused()
  await expect(sheet(page)).toBeVisible()
  await mark.click()
  await page.getByRole('menuitem', { name: 'Mark all as seen', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: /^Mark \d+ posts? as seen\?$/ })
  await expect(confirmation).toBeVisible()
  await physicalBracket(page)
  await page.keyboard.press('/')
  await expect(confirmation).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(confirmation).toHaveCount(0)
  await expect(sheet(page)).toBeVisible()
  await expect(mark).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toHaveCount(0)
  await expect(toggle(page)).toBeFocused()
  await openMobileSidebar(page)
  await page.mouse.click(385, 100)
  await expect(sheet(page)).toHaveCount(0)
  await expect(toggle(page)).toBeFocused()
})

test('same-row selection closes the sheet without replacing or pausing the reader', async ({
  page,
  corpus,
}) => {
  await seedPreference(page, JSON.stringify({ width: 500, collapsed: true }))
  await openPost(page, corpus, POSTS.reader, 'tag=pager')
  const reader = requireFixture(await pane(page).elementHandle())
  const article = requireFixture(await pane(page).locator('article').elementHandle())
  const audio = pane(page).locator('audio').first()
  const player = requireFixture(await audio.elementHandle())
  await readyPlayer(audio)
  await audio.evaluate(async (element: HTMLMediaElement) => {
    element.muted = true
    element.currentTime = 2
    await element.play()
  })
  await pane(page).evaluate((element) => {
    element.scrollTop = 120
  })
  await openMobileSidebar(page)
  await expect(sheet(page).locator('aside')).toHaveCount(1)
  expect(
    await player.evaluate((element) => element instanceof HTMLMediaElement && !element.paused),
  ).toBe(true)
  await sheet(page).locator(`[data-post-id="${POSTS.reader}"]`).click()
  await expect(sheet(page)).toHaveCount(0)
  await expect(toggle(page)).toBeFocused()
  expect(
    await reader.evaluate(
      (element) => element === document.querySelector('[aria-label="Selected post"]'),
    ),
  ).toBe(true)
  expect(
    await article.evaluate(
      (element) => element === document.querySelector('[aria-label="Selected post"] article'),
    ),
  ).toBe(true)
  expect(
    await player.evaluate(
      (element) =>
        element instanceof HTMLMediaElement &&
        element === document.querySelector('[aria-label="Selected post"] audio') &&
        !element.paused &&
        element.currentTime >= 2,
    ),
  ).toBe(true)
  expect(await pane(page).evaluate((element) => element.scrollTop)).toBe(120)
  expect(await savedPreference(page)).toEqual({ width: 500, collapsed: true })
  await openMobileSidebar(page)
  await sheet(page).locator(`[data-post-id="${POSTS.before}"]`).click()
  await expect(sheet(page)).toHaveCount(0)
  await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText('Earlier tied post')
  expect(new URL(page.url()).searchParams.get('tag')).toBe('pager')
})

test('unsent search survives closing and docking while Clear discards the draft', async ({
  page,
  corpus,
}) => {
  await page.clock.install({ time: new Date('2024-02-02T08:00:00Z') })
  await openPost(page, corpus, POSTS.reader)
  await openMobileSidebar(page)
  await page.clock.pauseAt(new Date('2024-02-02T10:00:00Z'))
  const input = timeline(page).getByRole('textbox', { name: 'Search posts' })
  await input.fill('draft across placement')
  expect(new URL(page.url()).searchParams.has('q')).toBe(false)
  await closeMobileSidebar(page)
  await openMobileSidebar(page)
  await expect(input).toHaveValue('draft across placement')
  expect(new URL(page.url()).searchParams.has('q')).toBe(false)
  await page.setViewportSize({ width: 820, height: 1180 })
  await expect(sheet(page)).toHaveCount(0)
  await expect(input).toHaveValue('draft across placement')
  await page.clock.runFor(250)
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('draft across placement')
  await page.setViewportSize({ width: 390, height: 844 })
  await openMobileSidebar(page)
  await expect(input).toHaveValue('draft across placement')
  await input.fill('discard this unsent draft')
  await timeline(page).getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(input).toHaveValue('')
  await page.clock.runFor(250)
  expect(new URL(page.url()).search).toBe('')
})

test('Media and docking close the sheet without delayed focus into hidden controls', async ({
  page,
  corpus,
}) => {
  await seedPreference(page, JSON.stringify({ width: 500, collapsed: false }))
  await openPost(page, corpus, POSTS.reader)
  const tabs = page.getByRole('navigation', { name: 'Author', exact: true })
  await tabs.getByRole('link', { name: 'Media', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Author media' })).toBeVisible()
  await page.goBack()
  await openMobileSidebar(page)
  await sheet(page).getByRole('button', { name: 'Mark posts', exact: true }).click()
  await page.goForward()
  await expect(sheet(page)).toHaveCount(0)
  await expect(page.getByRole('menu')).toHaveCount(0)
  await frames(page, 3)
  expect(
    await page.evaluate(
      () =>
        document.activeElement?.closest('[inert], [aria-hidden="true"], [data-tab="posts"]') ===
        null,
    ),
  ).toBe(true)
  await expect(toggle(page)).toBeDisabled()
  await expect(toggle(page)).toBeHidden()
  await blurControl(page)
  await physicalBracket(page)
  await page.keyboard.press('/')
  await expect(sheet(page)).toHaveCount(0)
  await page.setViewportSize({ width: 820, height: 1180 })
  await tabs.getByRole('link', { name: 'Posts', exact: true }).click()
  await expect(postElement(page)).toBeVisible()
  expect(await savedPreference(page)).toEqual({ width: 500, collapsed: false })
  await page.setViewportSize({ width: 390, height: 844 })
  await expectFullMobilePost(page)
  await openMobileSidebar(page)
  await sheet(page).getByRole('button', { name: 'Mark posts', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Mark all as seen', exact: true }).click()
  await expect(page.getByRole('dialog', { name: /^Mark \d+ posts? as seen\?$/ })).toBeVisible()
  await page.setViewportSize({ width: 820, height: 1180 })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await frames(page, 3)
  expect(
    await page.evaluate(
      () => document.activeElement?.closest('[inert], [aria-hidden="true"]') === null,
    ),
  ).toBe(true)
  await page.setViewportSize({ width: 390, height: 844 })
  await expectFullMobilePost(page)
  await expect(sheet(page)).toHaveCount(0)
})
