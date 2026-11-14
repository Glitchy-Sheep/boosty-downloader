import { expect, origin, test } from './fixtures'
import {
  API_PATH, AUTHOR_PATH, actualPosts, expectRows, expectSelected, expectStickyMonth, installTimeline,
  largeRows, pane, postPath, row, rows, sidebar,
} from './timeline-fixtures'

test('the 5000-row timeline renders a few screens and keeps its scroll on row navigation', async ({ page }) => {
  const posts = largeRows()
  const selectedIndex = posts.findIndex((post, index) => index > 2400 && new Date(post.created_at).getUTCDate() === 15)
  const selected = posts[selectedIndex]
  await installTimeline(page, posts)
  await page.goto(`${origin()}${postPath(selected.id)}`)
  await expectSelected(page, selected)
  await expect(row(page, selected.id)).toBeInViewport()
  await expect(row(page, selected.id)).toHaveAttribute('aria-current', 'page')
  expect(await rows(page).count()).toBeLessThan(100)
  const scroller = sidebar(page).locator('[data-post-list]')
  expect(await scroller.evaluate(element => element.scrollHeight)).toBeGreaterThan(200_000)
  const original = await scroller.elementHandle()
  const next = row(page, posts[selectedIndex + 1].id)
  await expect(next).toBeInViewport()
  const before = await scroller.evaluate(element => element.scrollTop)
  await next.click()
  await expectSelected(page, posts[selectedIndex + 1])
  expect(await original!.evaluate(element => element.isConnected)).toBe(true)
  expect(Math.abs(await scroller.evaluate(element => element.scrollTop) - before)).toBeLessThanOrEqual(1)
  await page.goBack()
  await expectSelected(page, selected)
  expect(Math.abs(await scroller.evaluate(element => element.scrollTop) - before)).toBeLessThanOrEqual(1)
  const activeMonth = await expectStickyMonth(page, posts)
  await scroller.evaluate(element => { element.scrollTop += 10 })
  expect(await expectStickyMonth(page, posts)).toBe(activeMonth)
  const rowHeight = await row(page, selected.id).evaluate(element => element.getBoundingClientRect().height)
  const crossed = page.waitForFunction(({ id, month }) => {
    const element = document.querySelector(`[data-post-list] [data-month="${month}"]`)
    const oldRow = document.querySelector(`[data-post-id="${id}"]`)
    return element === null && oldRow === null
  }, { id: selected.id, month: activeMonth })
  await scroller.evaluate((element, distance) => { element.scrollTop += distance }, rowHeight * 40)
  await crossed
  expect(await expectStickyMonth(page, posts)).not.toBe(activeMonth)
  await scroller.evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect(row(page, posts.at(-1)!.id)).toBeInViewport()
  expect(await rows(page).count()).toBeLessThan(100)
})

test('search snippets keep distinct row heights and literal markup inert', async ({ page }) => {
  const posts = largeRows(120).map((post, index) => ({
    ...post,
    title: `<script>window.timelineInjected=1</script> title ${index}`,
    match: {
      title: [{ text: '<script>', matched: true }, { text: `window.timelineInjected=1</script> title ${index}`, matched: false }],
      text: index % 2 === 0 ? [
        { text: 'Before a long snippet with ', matched: false },
        { text: '<img src=x onerror=window.timelineInjected=2>', matched: true },
        { text: ' and more readable words that should occupy two lines without overlapping the following row.', matched: false },
      ] : null,
    },
  }))
  await installTimeline(page, posts)
  await page.goto(`${origin()}${postPath(posts[0].id, 'q=script')}`)
  await expectSelected(page, posts[0])
  await expect(row(page, posts[0].id).locator('mark')).toHaveText(['<script>', '<img src=x onerror=window.timelineInjected=2>'])
  expect(await sidebar(page).locator('script, img[src="x"]').count()).toBe(0)
  expect(await page.evaluate(() => 'timelineInjected' in window)).toBe(false)
  const geometry = await rows(page).evaluateAll(nodes => nodes.map(node => {
    const bounds = node.getBoundingClientRect()
    return { id: node.getAttribute('data-post-id'), top: bounds.top, bottom: bounds.bottom, height: bounds.height }
  }))
  for (let index = 1; index < geometry.length; index += 1) {
    expect(geometry[index].top).toBeGreaterThanOrEqual(geometry[index - 1].bottom - 1)
  }
  const snippet = geometry.find(value => value.id === posts[0].id)!
  const titleOnly = geometry.find(value => value.id === posts[1].id)!
  expect(snippet.height).toBeGreaterThan(titleOnly.height)
})

test.describe('UTC month labels', () => {
  test.use({ timezoneId: 'America/Los_Angeles' })
  test('month grouping follows the API even on another local calendar date', async ({ page }) => {
    const posts = largeRows(2)
    posts[0].created_at = '2026-02-01T00:05:00Z'
    posts[1].created_at = '2026-01-31T23:55:00Z'
    await installTimeline(page, posts)
    await page.goto(`${origin()}${AUTHOR_PATH}`)
    await expectSelected(page, posts[0])
    await expect(sidebar(page).locator('[data-month="2026-02"]')).toContainText('February')
    await expect(sidebar(page).locator('[data-month="2026-01"]')).toContainText('January')
    await expectRows(page, posts)
  })
})

test('numeric search and tag strings remain exact in the address and controls', async ({ page }) => {
  const posts = largeRows(2)
  await installTimeline(page, posts)
  await page.route(`**${API_PATH}/tags`, route => route.fulfill({ json: [{ tag: '0012', count: 2 }] }))
  await page.goto(`${origin()}${postPath(posts[0].id, 'q=0012&tag=0012')}`)
  await expectSelected(page, posts[0])
  await expect(sidebar(page).getByRole('textbox', { name: 'Search posts' })).toHaveValue('0012')
  await expect(sidebar(page).getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue('0012')
  expect(new URL(page.url()).searchParams.get('q')).toBe('0012')
  expect(new URL(page.url()).searchParams.get('tag')).toBe('0012')
  await row(page, posts[1].id).click()
  await expectSelected(page, posts[1])
  expect(new URL(page.url()).searchParams.get('q')).toBe('0012')
  expect(new URL(page.url()).searchParams.get('tag')).toBe('0012')
})

test('a current post remains readable when an actual filter excludes it', async ({ page }) => {
  const posts = await actualPosts(page)
  const selected = posts.rows.find(post => post.access === 'open')!
  await page.goto(`${origin()}${postPath(selected.id)}`)
  await expectSelected(page, selected)
  await sidebar(page).getByRole('button', { name: 'Locked', exact: true }).click()
  await expectRows(page, (await actualPosts(page, 'locked=1')).rows)
  await expectSelected(page, selected)
  await expect(sidebar(page).locator('[aria-current="page"]')).toHaveCount(0)
})

test('an empty author keeps the filter controls available', async ({ page }) => {
  await installTimeline(page, [])
  await page.goto(`${origin()}${AUTHOR_PATH}`)
  await expect(sidebar(page)).toContainText(/no posts/i)
  await expect(sidebar(page).getByRole('textbox', { name: 'Search posts' })).toBeVisible()
  await expect(rows(page)).toHaveCount(0)
  expect(new URL(page.url()).pathname.replace(/\/$/, '')).toBe(AUTHOR_PATH)
})

for (const title of ['', '   ']) {
  test(`a ${JSON.stringify(title)} title has a named row and matching destination heading`, async ({ page }) => {
    const posts = largeRows(2)
    posts[0].title = title
    posts[0].match = { title: [], text: null }
    await installTimeline(page, posts)
    await page.goto(`${origin()}${postPath(posts[1].id)}`)
    await expect(row(page, posts[0].id)).toHaveAccessibleName('Untitled post')
    await row(page, posts[0].id).click()
    await expectSelected(page, posts[0])
  })
}

test('a thumbnail loads through the server and an unavailable image keeps the row readable', async ({ page }) => {
  const posts = await actualPosts(page)
  const selected = posts.rows.find(post => post.cover_path !== null)!
  const path = `/thumbs/pixel_forge/${selected.id}`
  await page.goto(`${origin()}${postPath(selected.id)}`)
  const image = row(page, selected.id).locator('img')
  await expect(image).toHaveAttribute('src', path)
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true)
  const before = await row(page, selected.id).boundingBox()
  await page.route(`**${path}`, route => route.fulfill({ status: 404, body: '' }))
  await page.reload()
  await expect(row(page, selected.id).locator('img')).toHaveCount(0)
  await expect(row(page, selected.id)).toContainText(selected.title)
  const after = await row(page, selected.id).boundingBox()
  expect(Math.abs(before!.height - after!.height)).toBeLessThanOrEqual(1)
  await expect(pane(page)).toBeVisible()
})

test('the browser follows the thumbnail route fallback to the original local image', async ({ page }) => {
  const posts = await actualPosts(page)
  const selected = posts.rows.find(post => post.cover_path !== null)!
  const target = `/media/pixel_forge/${selected.cover_path!.split('/').map(encodeURIComponent).join('/')}`
  await page.route(`**/thumbs/pixel_forge/${selected.id}`, route => route.fulfill({ status: 302, headers: { Location: target } }))
  const original = page.waitForResponse(response => new URL(response.url()).pathname === target && response.ok())
  await page.goto(`${origin()}${postPath(selected.id)}`)
  await original
  await expect.poll(() => row(page, selected.id).locator('img').evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true)
})

for (const scope of ['author', 'list', 'detail', 'tags'] as const) {
  test(`${scope} request failure can be retried without losing the destination`, async ({ page }) => {
    const posts = await actualPosts(page)
    const selected = posts.rows[0]
    const endpoints = { author: API_PATH, list: `${API_PATH}/posts`, detail: `${API_PATH}/posts/${selected.id}`, tags: `${API_PATH}/tags` }
    const message = `The ${scope} could not be loaded.`
    let fail = true
    await page.route(`**${endpoints[scope]}`, route => {
      if (fail) return route.fulfill({ status: 503, json: { error: { code: 'temporary_failure', message } } })
      return route.continue()
    })
    await page.goto(`${origin()}${postPath(selected.id)}`)
    await expect(page.getByText(message, { exact: true })).toBeVisible()
    if (scope === 'list' || scope === 'tags') await expectSelected(page, selected)
    fail = false
    const retry = { author: 'Try again', list: 'Retry posts', detail: 'Try again', tags: 'Retry tags' }[scope]
    await page.getByRole('button', { name: retry, exact: true }).click()
    await expectSelected(page, selected)
    await expectRows(page, posts.rows)
    await expect(page.getByText(message, { exact: true })).toHaveCount(0)
  })
}

test('unknown author and post errors remain recoverable', async ({ page }) => {
  await page.goto(`${origin()}/a/not-a-saved-author`)
  await expect(page.getByRole('alert')).toContainText(/not found/i)
  await page.getByRole('link', { name: 'Authors', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Authors', exact: true })).toBeVisible()
  await page.goto(`${origin()}${postPath('00000000-0000-4000-8000-999999999999')}`)
  await expect(pane(page).getByRole('alert')).toContainText(/not found/i)
  const posts = await actualPosts(page)
  await row(page, posts.rows[0].id).click()
  await expectSelected(page, posts.rows[0])
})

test('retrying the sidebar at author entry recovers the index redirect', async ({ page }) => {
  const posts = await actualPosts(page)
  let fail = true
  await page.route(`**${API_PATH}/posts`, route => {
    if (fail) return route.fulfill({ status: 503, json: { error: { code: 'temporary_failure', message: 'The timeline is temporarily unavailable.' } } })
    return route.continue()
  })
  await page.goto(`${origin()}${AUTHOR_PATH}`)
  await expect(sidebar(page).getByRole('alert')).toHaveText('The timeline is temporarily unavailable.')
  expect(new URL(page.url()).pathname.replace(/\/$/, '')).toBe(AUTHOR_PATH)
  fail = false
  await sidebar(page).getByRole('button', { name: 'Retry posts', exact: true }).click()
  await expectSelected(page, posts.rows[0])
  await expectRows(page, posts.rows)
  await expect(page.getByRole('alert')).toHaveCount(0)
})
