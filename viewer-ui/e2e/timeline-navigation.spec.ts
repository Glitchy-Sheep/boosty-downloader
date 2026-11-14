import { expect, openAuthors, origin, test } from './fixtures'
import {
  API_PATH, AUTHOR_PATH, actualPosts, actualTags, expectRows, expectSelected,
  pane, postPath, row, rows, sidebar,
} from './timeline-fixtures'

for (const width of [1440, 390]) {
  for (const colorScheme of ['dark', 'light'] as const) {
    test(`${width}px ${colorScheme}: an author card opens its newest post with the timeline`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 })
      await page.emulateMedia({ colorScheme })
      const posts = await actualPosts(page)
      await openAuthors(page)
      await page.getByRole('link', { name: 'Pixel Forge', exact: true }).click()
      await expectSelected(page, posts.rows[0])
      await expect(row(page, posts.rows[0].id)).toHaveAttribute('aria-current', 'page')
      await expectRows(page, posts.rows)
      await expect(page.getByRole('main')).toHaveCount(1)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1)).toBe(true)
      const locked = posts.rows.find(post => post.access === 'locked')!
      await expect(row(page, locked.id)).toContainText(locked.tier!)
      await expect(row(page, locked.id)).toContainText(/locked/i)
      await expect.poll(() => rows(page).locator('img').evaluateAll(images => images.every(image => {
        const loaded = image as HTMLImageElement
        return loaded.complete && loaded.naturalWidth > 0
      }))).toBe(true)
      const screenshot = testInfo.outputPath(`timeline-${width}-${colorScheme}.png`)
      await page.screenshot({ path: screenshot })
      await testInfo.attach(`timeline-${width}-${colorScheme}`, { path: screenshot, contentType: 'image/png' })
    })
  }
}

test('oldest-first entry respects the filtered order and does not add a redirect history entry', async ({ page }) => {
  const posts = await actualPosts(page, 'unseen=1&order=oldest')
  expect(posts.rows.length).toBeGreaterThan(1)
  await openAuthors(page)
  await page.goto(`${origin()}${AUTHOR_PATH}?unseen=1&order=oldest`)
  await expectSelected(page, posts.rows[0])
  await expectRows(page, posts.rows)
  await expect(sidebar(page).getByRole('button', { name: 'Unseen', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(sidebar(page).getByRole('combobox', { name: 'Sort order' })).toHaveValue('oldest')
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Authors', exact: true })).toBeVisible()
})

test('each media and state control filters the real indexed list', async ({ page }) => {
  const cases = [
    { label: 'Videos', query: 'kind=videos' },
    { label: 'Photos', query: 'kind=images' },
    { label: 'Audio', query: 'kind=audio' },
    { label: 'Files', query: 'kind=files' },
    { label: 'Unseen', query: 'unseen=1' },
    { label: 'Favorites', query: 'fav=1' },
    { label: 'Locked', query: 'locked=1' },
    { label: 'Incomplete', query: 'incomplete=1' },
  ]
  const unfiltered = await actualPosts(page)
  for (const choice of cases) {
    await page.goto(`${origin()}${AUTHOR_PATH}`)
    await expectSelected(page, unfiltered.rows[0])
    await sidebar(page).getByRole('button', { name: choice.label, exact: true }).click()
    const expected = await actualPosts(page, choice.query)
    await expectRows(page, expected.rows)
    const [key, value] = choice.query.split('=')
    await expect.poll(() => new URL(page.url()).searchParams.get(key)).toBe(value)
    await expect(sidebar(page).getByRole('button', { name: choice.label, exact: true })).toHaveAttribute('aria-pressed', 'true')
  }
})

test('combined filters survive reload, copied addresses, Back and Forward', async ({ page }) => {
  const tag = (await actualTags(page))[0].tag
  await page.goto(`${origin()}${AUTHOR_PATH}`)
  await sidebar(page).getByRole('button', { name: 'Videos', exact: true }).click()
  await sidebar(page).getByRole('button', { name: 'Unseen', exact: true }).click()
  await sidebar(page).getByRole('combobox', { name: 'Tag', exact: true }).selectOption(tag)
  const expected = await actualPosts(page, new URLSearchParams({ kind: 'videos', unseen: '1', tag }).toString())
  await expectRows(page, expected.rows)
  const copied = page.url()
  await page.reload()
  await expectRows(page, expected.rows)
  await expect(sidebar(page).getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue(tag)
  await expect(sidebar(page).getByRole('button', { name: 'Videos', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(sidebar(page).getByRole('button', { name: 'Unseen', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.goto(origin())
  await page.goto(copied)
  await expectRows(page, expected.rows)
  await sidebar(page).getByRole('button', { name: 'Unseen', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.has('unseen')).toBe(false)
  await page.goBack()
  await expectRows(page, expected.rows)
  await expect(sidebar(page).getByRole('button', { name: 'Unseen', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.goForward()
  await expect(sidebar(page).getByRole('button', { name: 'Unseen', exact: true })).toHaveAttribute('aria-pressed', 'false')
})

test('clearing all eight filters keeps a valid selected post outside the result', async ({ page }) => {
  const posts = await actualPosts(page)
  const selected = posts.rows[0]
  const query = new URLSearchParams({ q: 'no-such-library-text-98765', kind: 'videos', unseen: '1', fav: '1', tag: 'devlog', locked: '1', incomplete: '1', order: 'oldest' })
  await page.goto(`${origin()}${postPath(selected.id, query.toString())}`)
  await expectSelected(page, selected)
  await expect(rows(page)).toHaveCount(0)
  await expect(sidebar(page)).toContainText(/no posts match/i)
  await sidebar(page).getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect.poll(() => new URL(page.url()).search).toBe('')
  await expectRows(page, posts.rows)
  await expectSelected(page, selected)
  await expect(row(page, selected.id)).toHaveAttribute('aria-current', 'page')
})

test('selecting a row preserves filters and Back restores the previous post', async ({ page }) => {
  const posts = await actualPosts(page, 'kind=videos')
  expect(posts.rows.length).toBeGreaterThan(1)
  await page.goto(`${origin()}${postPath(posts.rows[0].id, 'kind=videos')}`)
  await expectSelected(page, posts.rows[0])
  await row(page, posts.rows[1].id).click()
  await expectSelected(page, posts.rows[1])
  expect(new URL(page.url()).searchParams.get('kind')).toBe('videos')
  await page.goBack()
  await expectSelected(page, posts.rows[0])
  await expect(row(page, posts.rows[0].id)).toHaveAttribute('aria-current', 'page')
  await page.getByRole('link', { name: 'Authors', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Authors', exact: true })).toBeVisible()
  expect(new URL(page.url()).search).toBe('')
})

test('typing shows the real title and body search runs while clearing restores all rows', async ({ page }) => {
  await page.goto(`${origin()}${AUTHOR_PATH}`)
  const search = sidebar(page).getByRole('textbox', { name: 'Search posts' })
  for (const query of ['Pixel', 'прототип', 'шейдер']) {
    await search.fill(query)
    const expected = await actualPosts(page, new URLSearchParams({ q: query }).toString())
    expect(expected.rows.length).toBeGreaterThan(0)
    await expectRows(page, expected.rows)
    await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe(query)
    for (const post of expected.rows) {
      const hits = [...post.match!.title, ...(post.match!.text ?? [])].filter(run => run.matched).map(run => run.text)
      expect(hits.length).toBeGreaterThan(0)
      await expect(row(page, post.id).locator('mark')).toHaveText(hits)
    }
  }
  await search.fill('')
  await expectRows(page, (await actualPosts(page)).rows)
  await expect.poll(() => new URL(page.url()).searchParams.has('q')).toBe(false)
})

test('a delayed obsolete search cannot replace the newest search result', async ({ page }) => {
  const oldResult = await actualPosts(page, 'q=Pixel')
  const newResult = await actualPosts(page, 'q=прототип')
  let release: () => void = () => {}
  const delayed = new Promise<void>(resolve => { release = resolve })
  let oldRequests = 0
  let oldReplyFinished = false
  await page.route(`**${API_PATH}/posts?*`, async route => {
    const query = new URL(route.request().url()).searchParams.get('q')
    if (query === 'Pixel') {
      oldRequests += 1
      await delayed
      try {
        await route.fulfill({ json: oldResult })
      } finally {
        oldReplyFinished = true
      }
    } else if (query === 'прототип') await route.fulfill({ json: newResult })
    else await route.continue()
  })
  await page.goto(`${origin()}${AUTHOR_PATH}`)
  const search = sidebar(page).getByRole('textbox', { name: 'Search posts' })
  try {
    await search.fill('Pixel')
    await expect.poll(() => oldRequests).toBe(1)
    await search.fill('прототип')
    await expectRows(page, newResult.rows)
    await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('прототип')
  } finally {
    release()
  }
  await expect.poll(() => oldReplyFinished).toBe(true)
  await expectRows(page, newResult.rows)
  await expect(search).toHaveValue('прототип')
  await expect(pane(page)).toBeVisible()
})

test('Back and Forward restore the search input and cancel unsent typing', async ({ page }) => {
  await page.goto(`${origin()}${AUTHOR_PATH}`)
  const search = sidebar(page).getByRole('textbox', { name: 'Search posts' })
  await search.fill('Pixel')
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('Pixel')
  await sidebar(page).getByRole('button', { name: 'Unseen', exact: true }).click()
  await search.fill('прототип')
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('прототип')
  await page.goBack()
  await expect(search).toHaveValue('Pixel')
  await expectRows(page, (await actualPosts(page, 'q=Pixel')).rows)
  await page.goForward()
  await expect(search).toHaveValue('прототип')
  await expectRows(page, (await actualPosts(page, 'q=прототип&unseen=1')).rows)
  await search.fill('unsent text')
  await page.goBack()
  await expect(search).toHaveValue('Pixel')
  await expectRows(page, (await actualPosts(page, 'q=Pixel')).rows)
  await page.waitForTimeout(300)
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('Pixel')
})

test('Clear filters discards unsent search text when the URL has no search yet', async ({ page }) => {
  const posts = await actualPosts(page)
  await page.goto(`${origin()}${AUTHOR_PATH}`)
  await expectSelected(page, posts.rows[0])
  await sidebar(page).getByRole('button', { name: 'Videos', exact: true }).click()
  const search = sidebar(page).getByRole('textbox', { name: 'Search posts' })
  await search.fill('unsent search text')
  expect(new URL(page.url()).searchParams.has('q')).toBe(false)
  await sidebar(page).getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(search).toHaveValue('')
  await page.waitForTimeout(300)
  expect(new URL(page.url()).search).toBe('')
  await expectRows(page, posts.rows)
})
