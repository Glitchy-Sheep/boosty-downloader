import { actualAuthors, card, expect, openAuthors, origin, storage, test } from './fixtures'

test('cards expose one title and a complete storage description to assistive technology', async ({ page, browserName }) => {
  const authors = await actualAuthors(page)
  authors[0] = { ...authors[0], title: 'Accessible artist', unseen: 12, storage: {
    videos: 240_000_000_000, images: 20_000_000_000, audio: 2_000_000_000, files: 1_000_000_000,
  } }
  const description = '263 GB of media on disk: videos 240 GB, photos 20 GB, audio 2 GB, files 1 GB. 12 unseen.'
  await openAuthors(page, authors)
  await expect(card(page, authors[0])).toHaveAccessibleName('Accessible artist')
  await expect(card(page, authors[0])).toHaveAccessibleDescription(description)
  for (const image of await card(page, authors[0]).locator('img').all()) await expect(image).toHaveAttribute('alt', '')
  if (browserName === 'chromium') {
    const session = await page.context().newCDPSession(page)
    try {
      const { nodes } = await session.send('Accessibility.getFullAXTree')
      const links = nodes.filter(node => node.role?.value === 'link' && node.name?.value === 'Accessible artist')
      expect(links).toHaveLength(1)
      expect(links[0].description?.value).toBe(description)
      const repeatedSummary = nodes.filter(node => !node.ignored && node.role?.value === 'StaticText' && node.name?.value === description)
      expect(repeatedSummary).toHaveLength(0)
    } finally {
      await session.detach()
    }
  }
})

test('keyboard focus reaches author links in reading order', async ({ page }) => {
  await openAuthors(page)
  const links = page.locator('a[href^="/a/"]')
  await page.getByRole('link', { name: 'Authors', exact: true }).focus()
  for (const link of await links.all()) {
    await page.keyboard.press('Tab')
    await expect(link).toBeFocused()
  }
})

test('forced colors preserve distinguishable bars and their text legends', async ({ page }) => {
  await page.emulateMedia({ forcedColors: 'active' })
  await openAuthors(page)
  const bar = storage(page).locator('[data-storage-bar]')
  await expect(bar).toHaveCSS('forced-color-adjust', 'none')
  const colors = await bar.locator('[data-kind]').evaluateAll(parts => parts.map(part => getComputedStyle(part).backgroundColor))
  expect(new Set(colors).size).toBe(4)
  expect(colors).not.toContain('rgba(0, 0, 0, 0)')
  for (const item of await storage(page).locator('li').all()) await expect(item).toBeVisible()
})

test('absent and failed decorative artwork keep initials and card layout', async ({ page }) => {
  const authors = await actualAuthors(page)
  authors[0] = { ...authors[0], title: 'Without Artwork', avatar_url: null, cover_url: null }
  authors[1] = { ...authors[1], title: 'Broken Artwork', avatar_url: '/missing-avatar', cover_url: '/missing-cover' }
  let release: () => void = () => {}
  const responseGate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/missing-*', async route => {
    await responseGate
    await route.fulfill({ status: 404, body: '' })
  })
  await page.route('**/api/authors', route => route.fulfill({ json: authors }))
  await page.goto(origin(), { waitUntil: 'domcontentloaded' })
  const broken = card(page, authors[1])
  await expect(broken).toBeVisible()
  const geometry = () => broken.evaluate(element => {
    const measure = (node: Element) => {
      const { x, y, width, height } = node.getBoundingClientRect()
      return { x, y, width, height }
    }
    return {
      card: measure(element),
      cover: measure(element.querySelector('div[aria-hidden="true"]')!),
      avatar: measure(element.querySelector('span[aria-hidden="true"]')!),
      storage: measure(element.querySelector('[data-storage]')!),
    }
  })
  const before = await geometry().finally(release)
  await expect(card(page, authors[0]).getByText('WA', { exact: true })).toBeVisible()
  await expect(broken.getByText('BA', { exact: true })).toBeVisible()
  await expect(broken.locator('img')).toHaveCount(0)
  const after = await geometry()
  for (const part of ['card', 'cover', 'avatar', 'storage'] as const) {
    for (const dimension of ['x', 'y', 'width', 'height'] as const) {
      expect(Math.abs(after[part][dimension] - before[part][dimension]), `${part}.${dimension}`).toBeLessThanOrEqual(2)
    }
  }
  for (const author of authors.slice(0, 2)) {
    await expect(card(page, author)).toHaveAccessibleName(author.title)
    await expect(storage(page, author)).toBeVisible()
  }
})
