import type { Page } from '@playwright/test'

import { actualAuthors, card, checkStorage, expect, openAuthors, origin, storage, sumStorage, test } from './fixtures'

async function checkOverflow(page: Page): Promise<void> {
  const overflow = await page.locator('a[href^="/a/"]').evaluateAll(cards => cards.map(card => {
    const boundary = card.getBoundingClientRect()
    const children = [...card.querySelectorAll('h2, p, li, [data-storage-bar], [data-storage] + div span')]
    return Math.max(0, ...children.map(child => Math.max(
      child.getBoundingClientRect().right - boundary.right,
      child.scrollWidth - child.clientWidth,
    )))
  }))
  expect(overflow.every(pixels => pixels <= 0.5), `Card overflow: ${overflow}`).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollHeight - innerHeight)).toBeLessThanOrEqual(1)
}

test('the packaged CLI serves real author totals and local artwork', async ({ page }) => {
  const authors = await actualAuthors(page)
  expect(authors).toHaveLength(3)
  await openAuthors(page)
  await expect(page.locator('a[href^="/a/"]')).toHaveCount(authors.length)
  const ordered = [...authors].sort((a, b) => (a.title || a.name).localeCompare(b.title || b.name) || a.name.localeCompare(b.name))
  await expect(page.locator('a[href^="/a/"] h2')).toHaveText(ordered.map(author => author.title || author.name))
  const posts = authors.reduce((sum, author) => sum + author.posts, 0)
  const unseen = authors.reduce((sum, author) => sum + author.unseen, 0)
  await expect(page.getByText(`3 authors · ${posts} posts · ${unseen} unseen`, { exact: true })).toBeVisible()
  await checkStorage(storage(page), sumStorage(authors))
  for (const author of authors) {
    await expect(card(page, author)).toHaveAccessibleName(author.title || author.name)
    await checkStorage(storage(page, author), author.storage)
    for (const source of [author.avatar_url, author.cover_url]) {
      expect(source).not.toBeNull()
      await expect.poll(() => card(page, author).locator(`img[src="${source}"]`).evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true)
    }
  }
})

for (const width of [1440, 1024, 820, 390, 360]) {
  for (const colorScheme of ['dark', 'light'] as const) {
    test(`${width}px ${colorScheme}: responsive cards and storage`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 })
      await page.emulateMedia({ colorScheme })
      await openAuthors(page)
      await expect(page.locator('html')).toHaveCSS('color-scheme', colorScheme)
      await checkOverflow(page)
      const heading = await page.getByRole('heading', { name: 'Authors', exact: true }).boundingBox()
      const library = await storage(page).boundingBox()
      expect(heading).not.toBeNull()
      expect(library).not.toBeNull()
      if (width >= 1024) expect(library!.x).toBeGreaterThan(heading!.x + heading!.width)
      else expect(library!.y).toBeGreaterThan(heading!.y + heading!.height)
      const rows = await storage(page).locator('li').evaluateAll(items => new Set(items.map(item => Math.round(item.getBoundingClientRect().top))).size)
      expect(rows).toBe(width < 640 ? 2 : 1)
      const firstRow = await page.locator('a[href^="/a/"]').evaluateAll(cards => {
        const tops = cards.map(card => Math.round(card.getBoundingClientRect().top))
        return tops.filter(top => top === tops[0]).length
      })
      const columns = width >= 1440 ? 3 : width >= 820 ? 2 : 1
      expect(firstRow).toBe(columns)
      if (width === 1440 || width === 390) {
        await expect.poll(() => page.locator('img').evaluateAll(images => images.every(image => (image as HTMLImageElement).complete))).toBe(true)
        const screenshot = testInfo.outputPath(`authors-${width}-${colorScheme}.png`)
        await page.screenshot({ path: screenshot, fullPage: true })
        await testInfo.attach(`authors-${width}-${colorScheme}`, { path: screenshot, contentType: 'image/png' })
      }
    })
  }
}

test('mobile scrolling reaches the last card while the header stays visible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 1000 })
  await openAuthors(page)
  await checkOverflow(page)
  const scroller = page.locator('main > div')
  const lastCard = page.locator('a[href^="/a/"]').last()
  await page.mouse.move(195, 800)
  await page.mouse.wheel(0, 3000)
  await expect.poll(() => scroller.evaluate(element => element.scrollTop + element.clientHeight >= element.scrollHeight - 1)).toBe(true)
  await expect(lastCard).toBeInViewport({ ratio: 1 })
  await page.mouse.wheel(0, 3000)
  await expect(page.locator('header')).toBeInViewport({ ratio: 1 })
  expect(await page.evaluate(() => scrollY)).toBe(0)

  await scroller.evaluate(element => { element.scrollTop = 0 })
  await page.getByRole('link', { name: 'Authors', exact: true }).focus()
  for (const link of await page.locator('a[href^="/a/"]').all()) {
    await page.keyboard.press('Tab')
    if (await scroller.evaluate(element => document.activeElement === element)) await page.keyboard.press('Tab')
    await expect(link).toBeFocused()
  }
  await expect(lastCard).toBeInViewport({ ratio: 1 })
  await expect(page.locator('header')).toBeInViewport({ ratio: 1 })
  expect(await page.evaluate(() => scrollY)).toBe(0)
})

test('loading, structured API error and retry recover to authors', async ({ page }) => {
  const authors = await actualAuthors(page)
  let fail = true
  let release: () => void = () => {}
  const responseGate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/authors', async route => {
    await responseGate
    if (fail) await route.fulfill({ status: 503, json: { error: { code: 'library_unavailable', message: 'The library is temporarily unavailable.' } } })
    else await route.fulfill({ json: authors })
  })
  await page.goto(origin(), { waitUntil: 'domcontentloaded' })
  try {
    await expect(page.getByRole('status')).toHaveText('Loading authors...')
  } finally {
    release()
  }
  await expect(page.getByRole('alert')).toHaveText('The library is temporarily unavailable.')
  fail = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('heading', { name: 'Authors', exact: true })).toBeVisible()
  await expect(page.locator('a[href^="/a/"]')).toHaveCount(authors.length)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('an empty library explains how to add authors', async ({ page }) => {
  await openAuthors(page, [])
  await expect(page.getByRole('status')).toHaveText('No authors yet. Download posts to this library to see them here.')
  await expect(page.locator('[data-storage]')).toHaveCount(0)
})

test('long titles, missing descriptions and unbroken text preserve card geometry', async ({ page }) => {
  const authors = await actualAuthors(page)
  authors[0].title = 'Мастерская цифровой живописи, концепт-арта и пиксель-арта'
  authors[1].description = ''
  await openAuthors(page, authors)
  const rows = await page.locator('a[href^="/a/"] [data-storage]').evaluateAll(blocks => blocks.map(block => ({
    storage: block.getBoundingClientRect().top,
    footer: block.nextElementSibling!.getBoundingClientRect().top,
  })))
  for (const part of ['storage', 'footer'] as const) {
    const heights = rows.map(row => row[part])
    expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(2)
  }
  authors[0].title = 'Pixelforgeconceptartandshaderlaboratoryworkshop'
  authors[0].description = 'https://example.test/a/verylongunbrokenlinkwithnomidwordseparatorsthatmuststayinsidethecard'
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await openAuthors(page, authors)
    await checkOverflow(page)
  }
})
