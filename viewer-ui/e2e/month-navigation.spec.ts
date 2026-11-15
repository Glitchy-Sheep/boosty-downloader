import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'

import type { Locator, Page } from '@playwright/test'

import type { PostList, PostRow } from '../src/lib/api.gen'
import { expect, test, type PostCorpus } from './post-fixtures'
import { requireFixture } from './required-fixture'

import { openMobileSidebar, postElement as pane } from './mobile-sidebar-fixtures'

const AUTHOR = 'month_checks'
const API = `/api/authors/${AUTHOR}`
type Order = 'newest' | 'oldest'
type ViewportSnapshot = {
  top: number
  bottom: number
  sticky: string | null
  stickyBottom: number
  value: string | null
  target: { top: number; bottom: number } | null
}

function sidebar(page: Page): Locator {
  return page.getByRole('complementary', { name: 'Posts of Month Checks' })
}

function scrubber(page: Page): Locator {
  return sidebar(page).getByRole('combobox', { name: 'Jump to month' })
}

function scroller(page: Page): Locator {
  return sidebar(page).locator('[data-post-list]')
}

function postPath(id: string): string {
  return `/a/${AUTHOR}/p/${id}`
}

function monthOf(post: PostRow): string {
  return new Date(post.created_at).toISOString().slice(0, 7)
}

async function posts(page: Page, corpus: PostCorpus, search = ''): Promise<PostRow[]> {
  const response = await page.request.get(`${corpus.origin}${API}/posts?${search}`)
  expect(response.ok()).toBe(true)
  return ((await response.json()) as PostList).rows
}

async function openPost(page: Page, corpus: PostCorpus, post: PostRow, search = '') {
  await page.goto(`${corpus.origin}${postPath(post.id)}${search ? `?${search}` : ''}`)
  await expect(pane(page).getByRole('heading', { level: 1, includeHidden: true })).toHaveText(
    post.title,
  )
  await openMobileSidebar(page)
  await expect(scrubber(page)).toBeEnabled()
  await expect(sidebar(page).getByLabel('Updating posts')).toHaveCount(0)
}

async function savedMarks(corpus: PostCorpus): Promise<Record<string, string>> {
  const author = path.join(corpus.library, AUTHOR)
  const files = (await readdir(author, { recursive: true }))
    .filter((file) => path.basename(file) === 'viewer.json')
    .sort()
  expect(files).toHaveLength(48)
  const records: Record<string, string> = {}
  for (const file of files) records[file] = await readFile(path.join(author, file), 'utf8')
  return records
}

/** Read the current virtual rows and sticky header in the same browser frame. */
function readViewport(element: Element, targetId: string): ViewportSnapshot {
  const bounds = element.getBoundingClientRect()
  const headers = [...element.querySelectorAll<HTMLElement>('[data-month]')]
  const sticky = headers.find(
    (header) => Math.abs(header.getBoundingClientRect().top - bounds.top) <= 1,
  )
  const target = element.querySelector(`[data-post-id="${targetId}"]`)?.getBoundingClientRect()
  const select = element
    .closest('aside')
    ?.querySelector<HTMLSelectElement>('select[aria-label="Jump to month"]')
  return {
    top: bounds.top,
    bottom: bounds.bottom,
    sticky: sticky?.getAttribute('data-month') ?? null,
    stickyBottom: sticky?.getBoundingClientRect().bottom ?? bounds.top,
    value: select?.value ?? null,
    target: target ? { top: target.top, bottom: target.bottom } : null,
  }
}

async function expectMonth(page: Page, post: PostRow): Promise<void> {
  await expect(async () => {
    const state = await scroller(page).evaluate(readViewport, post.id)
    const target = requireFixture(state.target)
    expect(state.sticky).toBeTruthy()
    expect(state.value).toBe(state.sticky)
    expect(target.top).toBeGreaterThanOrEqual(state.stickyBottom - 1)
    expect(target.top).toBeLessThan(state.bottom)
    expect(target.bottom).toBeGreaterThan(state.stickyBottom)
  }).toPass({ timeout: 5_000 })
}

async function jump(page: Page, rows: PostRow[], month: string): Promise<void> {
  await scrubber(page).selectOption(month)
  await expectMonth(page, requireFixture(rows.find((post) => monthOf(post) === month)))
}

async function expectChoices(page: Page, months: string[]): Promise<void> {
  await expect
    .poll(() =>
      scrubber(page)
        .locator('option')
        .evaluateAll((options) => options.map((option) => option.getAttribute('value'))),
    )
    .toEqual(months)
}

function searchFor(order: Order): string {
  return new URLSearchParams({
    q: 'archive',
    tag: 'archive',
    fav: '1',
    unseen: '1',
    ...(order === 'oldest' ? { order } : {}),
  }).toString()
}

for (const order of ['newest', 'oldest'] as const) {
  for (const width of [1440, 390]) {
    for (const colorScheme of ['dark', 'light'] as const) {
      test(`${order}, ${width}px ${colorScheme}: month jumps preserve the open page across seven years`, async ({
        page,
        corpus,
      }, testInfo) => {
        await page.setViewportSize({ width, height: 1000 })
        await page.emulateMedia({ colorScheme })
        const search = searchFor(order)
        const rows = await posts(page, corpus, search)
        expect(rows).toHaveLength(48)
        const selected = requireFixture(rows[0])
        const before = await savedMarks(corpus)
        await openPost(page, corpus, selected, search)
        const address = page.url()
        const body = requireFixture(await pane(page).locator('.post-body').elementHandle())
        await pane(page).evaluate((element) => {
          element.scrollTop = 120
        })
        const paneScroll = await pane(page).evaluate((element) => element.scrollTop)
        expect(paneScroll).toBeGreaterThan(0)
        const availableMonths = [...new Set(rows.map(monthOf))]
        await expectChoices(page, availableMonths)
        expect(await scrubber(page).locator('optgroup').count()).toBe(8)
        for (const month of ['2021-03', monthOf(requireFixture(rows.at(-1))), monthOf(selected)]) {
          await jump(page, rows, month)
          await expect(page).toHaveURL(address)
          await expect(
            pane(page).getByRole('heading', { level: 1, includeHidden: true }),
          ).toHaveText(selected.title)
          expect(await body.evaluate((element) => element.isConnected)).toBe(true)
          expect(await pane(page).evaluate((element) => element.scrollTop)).toBe(paneScroll)
        }
        expect(await savedMarks(corpus)).toEqual(before)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        )
        await jump(page, rows, '2021-03')
        const screenshot = testInfo.outputPath(`month-${order}-${width}-${colorScheme}.png`)
        await page.screenshot({ path: screenshot })
        await testInfo.attach('month navigation', { path: screenshot, contentType: 'image/png' })
      })
    }
  }

  test(`${order}: filtered month choices replace the old scroll indexes`, async ({
    page,
    corpus,
  }) => {
    const search = searchFor(order)
    const rows = await posts(page, corpus, search)
    const selected = requireFixture(rows.find((post) => monthOf(post) === '2023-10'))
    await openPost(page, corpus, selected, search)
    await jump(page, rows, '2021-05')
    await sidebar(page)
      .getByRole('combobox', { name: 'Tag', exact: true })
      .selectOption('milestone')
    await expect(sidebar(page).getByLabel('Updating posts')).toHaveCount(0)
    const filteredSearch = new URLSearchParams(search)
    filteredSearch.set('tag', 'milestone')
    const filtered = await posts(page, corpus, filteredSearch.toString())
    expect(filtered).toHaveLength(21)
    const months = [...new Set(filtered.map(monthOf))]
    await expectChoices(page, months)
    await expect(scrubber(page).locator('option[value="2021-05"]')).toHaveCount(0)
    for (const month of ['2021-03', monthOf(requireFixture(filtered.at(-1)))]) {
      await jump(page, filtered, month)
      expect(new URL(page.url()).pathname).toBe(postPath(selected.id))
      expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual(
        Object.fromEntries(filteredSearch),
      )
      await expect(pane(page).getByRole('heading', { level: 1, includeHidden: true })).toHaveText(
        selected.title,
      )
    }
    const nextOrder = order === 'newest' ? 'oldest' : 'newest'
    await sidebar(page).getByRole('combobox', { name: 'Sort order' }).selectOption(nextOrder)
    if (nextOrder === 'oldest') filteredSearch.set('order', 'oldest')
    else filteredSearch.delete('order')
    const reordered = await posts(page, corpus, filteredSearch.toString())
    await expectChoices(page, [...new Set(reordered.map(monthOf))])
    await expect(scrubber(page)).toBeEnabled()
    await jump(page, reordered, '2021-03')
    expect(new URL(page.url()).pathname).toBe(postPath(selected.id))
    expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual(
      Object.fromEntries(filteredSearch),
    )
    await expect(pane(page).getByRole('heading', { level: 1, includeHidden: true })).toHaveText(
      selected.title,
    )
  })

  test(`${order}: wheel scrolling updates the current month and permits another jump`, async ({
    page,
    corpus,
  }) => {
    const rows = await posts(page, corpus, searchFor(order))
    await openPost(page, corpus, requireFixture(rows[0]), searchFor(order))
    await jump(page, rows, '2021-03')
    const address = page.url()
    const before = await scroller(page).evaluate((element) => element.scrollTop)
    await scroller(page).hover()
    await page.mouse.wheel(0, 600)
    await expect
      .poll(() => scroller(page).evaluate((element) => element.scrollTop))
      .toBeGreaterThan(before + 100)
    await expect(async () => {
      const state = await scroller(page).evaluate(readViewport, '')
      expect(state.sticky).toBeTruthy()
      expect(state.sticky).not.toBe('2021-03')
      expect(state.value).toBe(state.sticky)
    }).toPass({ timeout: 5_000 })
    await jump(page, rows, '2021-03')
    await expect(page).toHaveURL(address)
  })
}

test('pending and failed filters cannot use stale month choices', async ({ page, corpus }) => {
  const rows = await posts(page, corpus)
  const selected = requireFixture(rows[0])
  await openPost(page, corpus, selected)
  await jump(page, rows, '2021-03')
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`**${API}/posts?*`, async (route) => {
    if (new URL(route.request().url()).searchParams.get('tag') !== 'milestone') {
      await route.continue()
      return
    }
    await gate
    await route.fulfill({
      status: 503,
      json: { error: { code: 'temporary_failure', message: 'Month list unavailable.' } },
    })
  })
  try {
    await sidebar(page)
      .getByRole('combobox', { name: 'Tag', exact: true })
      .selectOption('milestone')
    await expect(sidebar(page).getByLabel('Updating posts')).toBeVisible()
    await expect(scrubber(page)).toBeDisabled()
    expect(new URL(page.url()).pathname).toBe(postPath(selected.id))
  } finally {
    release()
  }
  await expect(sidebar(page).getByRole('alert')).toHaveText('Month list unavailable.')
  if (await scrubber(page).count()) await expect(scrubber(page)).toBeDisabled()
  await expect(pane(page).getByRole('heading', { level: 1, includeHidden: true })).toHaveText(
    selected.title,
  )
  await page.unroute(`**${API}/posts?*`)
  await sidebar(page).getByRole('button', { name: 'Retry posts' }).click()
  await expect(scrubber(page)).toBeEnabled()
  const filtered = await posts(page, corpus, 'tag=milestone')
  await jump(page, filtered, '2021-03')
})

test('empty results hide the control and one populated month remains navigable', async ({
  page,
  corpus,
}) => {
  const rows = await posts(page, corpus, 'tag=month-2021-03')
  expect(rows).toHaveLength(3)
  const selected = requireFixture(rows[0])
  await openPost(page, corpus, selected, 'tag=month-2021-03')
  await expect(scrubber(page).locator('option')).toHaveCount(1)
  await expect(scrubber(page)).toHaveValue('2021-03')
  await jump(page, rows, '2021-03')
  await sidebar(page)
    .getByRole('textbox', { name: 'Search posts' })
    .fill('no-matching-archive-98765')
  await expect(sidebar(page)).toContainText('No posts match the filters.')
  await expect(scrubber(page)).toHaveCount(0)
  await expect(pane(page).getByRole('heading', { level: 1, includeHidden: true })).toHaveText(
    selected.title,
  )
})

test('native month selection owns its keyboard input without changing the open post', async ({
  page,
  corpus,
}) => {
  const rows = await posts(page, corpus)
  await openPost(page, corpus, requireFixture(rows[0]))
  await jump(page, rows, '2021-03')
  const address = page.url()
  const input = sidebar(page).getByRole('textbox', { name: 'Search posts' })
  for (const key of ['j', 'k', '/']) {
    await scrubber(page).focus()
    await expect(scrubber(page)).toBeFocused()
    await page.keyboard.press(key)
    await expect(page).toHaveURL(address)
    await expect(input).not.toBeFocused()
  }
  await jump(page, rows, '2021-03')
  await sidebar(page).getByRole('combobox', { name: 'Sort order' }).focus()
  await page.keyboard.press('Tab')
  await expect(sidebar(page).getByRole('button', { name: 'Mark posts', exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(scrubber(page)).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expectMonth(page, requireFixture(rows.find((post) => monthOf(post) === '2020-11')))
  await expect(page).toHaveURL(address)
})

test('the month-start button returns to the current month by click and Enter', async ({
  page,
  corpus,
}) => {
  await page.setViewportSize({ width: 390, height: 600 })
  const rows = await posts(page, corpus, 'tag=month-2021-03')
  const first = requireFixture(rows[0])
  const before = await savedMarks(corpus)
  await openPost(page, corpus, first, 'tag=month-2021-03')
  const address = page.url()
  const body = requireFixture(await pane(page).locator('.post-body').elementHandle())
  const start = sidebar(page).getByRole('button', { name: 'Jump to month start' })
  await expectMonth(page, first)
  await expect
    .poll(() => scroller(page).evaluate((element) => element.scrollHeight - element.clientHeight))
    .toBeGreaterThan(30)
  for (const action of ['click', 'Enter'] as const) {
    await scroller(page).hover()
    await page.mouse.wheel(0, 90)
    await expect(async () => {
      const state = await scroller(page).evaluate(readViewport, first.id)
      expect(state.sticky).toBe('2021-03')
      expect(state.value).toBe('2021-03')
      expect(requireFixture(state.target).top).toBeLessThan(state.stickyBottom - 30)
    }).toPass({ timeout: 5_000 })
    if (action === 'click') await start.click()
    else {
      await start.focus()
      await expect(start).toBeFocused()
      await page.keyboard.press('Enter')
    }
    await expectMonth(page, first)
    await expect(page).toHaveURL(address)
    await expect(pane(page).getByRole('heading', { level: 1, includeHidden: true })).toHaveText(
      first.title,
    )
    expect(await body.evaluate((element) => element.isConnected)).toBe(true)
  }
  expect(await savedMarks(corpus)).toEqual(before)
})
