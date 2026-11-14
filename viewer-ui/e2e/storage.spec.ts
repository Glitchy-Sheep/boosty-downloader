import { actualAuthors, checkStorage, EMPTY_STORAGE, expect, openAuthors, storage, test } from './fixtures'

test('zero, single-kind and single-author storage have truthful summaries', async ({ page }) => {
  const authors = (await actualAuthors(page)).map(author => ({ ...author, storage: { ...EMPTY_STORAGE } }))
  await openAuthors(page, authors)
  await expect(storage(page)).toHaveCount(0)
  await expect(page.locator('[data-storage-bar]')).toHaveCount(0)
  await expect(page.getByText('No media on disk', { exact: true })).toHaveCount(3)

  const single = { ...authors[0], storage: { ...EMPTY_STORAGE, images: 45_200_000_000 } }
  await openAuthors(page, [single])
  await expect(storage(page)).toHaveCount(0)
  await expect(storage(page, single).locator('p')).toHaveText('45.2 GB of photos on disk')
  await checkStorage(storage(page, single), single.storage)

  single.storage.videos = 10_000_000_000
  await openAuthors(page, [single])
  await expect(storage(page, single).locator('p')).toHaveText('55.2 GB of media on disk')
  await checkStorage(storage(page, single), single.storage)
})

test('tiny media kinds remain visible without changing the other proportions', async ({ page }) => {
  const authors = (await actualAuthors(page)).map(author => ({ ...author, storage: {
    videos: 900_000_000, images: 100_000_000, audio: 1, files: 1,
  } }))
  await page.setViewportSize({ width: 360, height: 1000 })
  await openAuthors(page, authors)
  await checkStorage(storage(page), { videos: 2_700_000_000, images: 300_000_000, audio: 3, files: 3 })
  for (const author of authors) await checkStorage(storage(page, author), author.storage)
})

const boundaries = [
  { bytes: 999, decimal: '999 B', binary: '999 B' },
  { bytes: 1000, decimal: '1 KB', binary: '1000 B' },
  { bytes: 1023, decimal: '1.02 KB', binary: '1023 B' },
  { bytes: 1024, decimal: '1.02 KB', binary: '1 KB' },
  { bytes: 999_499, decimal: '999 KB', binary: '976 KB' },
  { bytes: 999_500, decimal: '1 MB', binary: '976 KB' },
  { bytes: 1_023_488, decimal: '1.02 MB', binary: '0.976 MB' },
  { bytes: 1_048_576, decimal: '1.05 MB', binary: '1 MB' },
  { bytes: 1_000_000_000, decimal: '1 GB', binary: '954 MB' },
  { bytes: 1_073_741_824, decimal: '1.07 GB', binary: '1 GB' },
  { bytes: 263_049_070_956, decimal: '263 GB', binary: '245 GB' },
  { bytes: 1_500_000_000_000, decimal: '1.5 TB', binary: '1.36 TB' },
]

for (const platform of [
  { name: 'decimal', userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)' },
  { name: 'binary', userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' },
] as const) {
  test.describe(platform.name, () => {
    test.use({ userAgent: platform.userAgent })
    test('units follow the browser platform at rounding boundaries', async ({ page }) => {
      const [template] = await actualAuthors(page)
      const authors = boundaries.map((boundary, index) => ({
        ...template, name: `boundary-${index}`, title: `Boundary ${index}`,
        avatar_url: null, cover_url: null, storage: { ...EMPTY_STORAGE, images: boundary.bytes },
      }))
      await openAuthors(page, authors)
      for (const [index, author] of authors.entries()) {
        await expect(storage(page, author).locator('p')).toHaveText(`${boundaries[index][platform.name]} of photos on disk`)
      }
    })
  })
}
