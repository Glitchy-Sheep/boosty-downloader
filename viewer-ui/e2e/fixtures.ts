import { expect, test as base, type Locator, type Page } from '@playwright/test'

import type { Author, MediaStorage } from '../src/lib/api.gen'

export const KINDS = ['videos', 'images', 'files', 'audio'] as const
export const LABELS: Record<keyof MediaStorage, string> = {
  videos: 'Videos', images: 'Photos', audio: 'Audio', files: 'Files',
}
export const EMPTY_STORAGE: MediaStorage = { videos: 0, images: 0, audio: 0, files: 0 }
export const test = base.extend<{ runtimeErrors: void }>({
  runtimeErrors: [async ({ page }, use) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin === origin()) return route.continue()
      errors.push(`Unexpected external request: ${route.request().url()}`)
      return route.abort()
    })
    await use()
    expect(errors, 'No runtime errors or external requests').toEqual([])
  }, { auto: true }],
})
export { expect }

export function origin(): string {
  const value = process.env.BOOSTY_VIEWER_E2E_ORIGIN
  if (!value) throw new Error('The isolated viewer setup did not publish its origin')
  return value
}

export function card(page: Page, author: Author): Locator {
  return page.locator(`a[href="/a/${encodeURIComponent(author.name)}"]`)
}

export function storage(page: Page, author?: Author): Locator {
  return page.locator(`[data-storage="${author?.name ?? ''}"]`)
}

export async function openAuthors(page: Page, authors?: Author[]): Promise<void> {
  if (authors) {
    await page.unroute('**/api/authors')
    await page.route('**/api/authors', route => route.fulfill({ json: authors }))
  }
  await page.goto(origin())
  await expect(page.getByRole('heading', { name: 'Authors', exact: true })).toBeVisible()
  if (authors) await expect(page.locator('a[href^="/a/"]')).toHaveCount(authors.length)
}

export async function actualAuthors(page: Page): Promise<Author[]> {
  const response = await page.request.get(`${origin()}/api/authors`)
  expect(response.ok()).toBe(true)
  return await response.json() as Author[]
}

export function total(storage: MediaStorage): number {
  return KINDS.reduce((sum, kind) => sum + storage[kind], 0)
}

export function sumStorage(authors: Author[]): MediaStorage {
  const result = { ...EMPTY_STORAGE }
  for (const author of authors) {
    for (const kind of KINDS) result[kind] += author.storage[kind]
  }
  return result
}

export function sizeMatches(text: string, bytes: number, base = 1000): boolean {
  const match = /^(\d+(?:\.\d+)?) (B|KB|MB|GB|TB)$/.exec(text)
  if (!match) return false
  const unit = ['B', 'KB', 'MB', 'GB', 'TB'].indexOf(match[2])
  const value = Number(match[1])
  if (unit === 0) return value === bytes
  const digits = match[1].replace('.', '').replace(/^0+/, '').length
  const represented = value * base ** unit
  return digits <= 3 && value < 1000 && Math.abs(represented - bytes) <= represented * 0.0051
}

export async function checkStorage(block: Locator, values: MediaStorage): Promise<void> {
  const kinds = KINDS.filter(kind => values[kind] > 0).sort((first, second) => values[second] - values[first])
  const lead = (await block.locator('p').first().innerText()).replace(/\s+/g, ' ').trim()
  expect(sizeMatches(lead.split(' of ')[0], total(values)), lead).toBe(true)
  const bar = block.locator('[data-storage-bar]')
  await expect(bar).toBeVisible()
  expect(await bar.locator('[data-kind]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-kind')))).toEqual(kinds)
  if (kinds.length === 1) {
    expect(lead).toContain(`of ${LABELS[kinds[0]].toLowerCase()}`)
    await expect(block.locator('li')).toHaveCount(0)
  } else {
    expect(await block.locator('li[data-kind]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-kind')))).toEqual(kinds)
    for (const kind of kinds) {
      const item = block.locator(`li[data-kind="${kind}"]`)
      await expect(item).toContainText(LABELS[kind])
      expect(sizeMatches((await item.innerText()).replace(LABELS[kind], '').replace(/\s+/g, ' ').trim(), values[kind])).toBe(true)
    }
  }
  const parts = await bar.locator('[data-kind]').evaluateAll(nodes => nodes.map(node => ({
    kind: node.getAttribute('data-kind') as keyof MediaStorage,
    width: node.getBoundingClientRect().width,
    height: node.getBoundingClientRect().height,
  })))
  expect(parts.every(part => part.width >= part.height / 2 - 0.5)).toBe(true)
  const proportional = parts.filter(part => part.width > part.height / 2 + 1)
  const width = proportional.reduce((sum, part) => sum + part.width, 0)
  const bytes = proportional.reduce((sum, part) => sum + values[part.kind], 0)
  for (const part of proportional) expect(Math.abs(part.width / width - values[part.kind] / bytes)).toBeLessThan(0.01)
}
