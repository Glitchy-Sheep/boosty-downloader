import {
  AUTHOR,
  capabilities,
  expect,
  expectDownload,
  expectOpen,
  localCapabilities,
  ofType,
  openFiles,
  openPost,
  requireFixture,
  test,
  watchRuntime,
  type RuntimeCheck,
} from './file-actions-fixtures'
import { openMedia } from './media-fixtures'

for (const width of [360, 390, 1024]) {
  test(`${width}px touch folds file, post and fullscreen actions without overflow`, async ({
    browser,
    corpus,
    recording,
  }) => {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: true })
    let runtime: RuntimeCheck | undefined
    try {
      const page = await context.newPage()
      runtime = await watchRuntime(page, corpus)
      await capabilities(page, localCapabilities(corpus))
      const data = await openFiles(page, corpus)
      const item = ofType(data, 'pdf')
      const row = page.locator(`[data-media-id="${item.id}"]`)
      expect(await page.evaluate(() => matchMedia('(hover: none)').matches)).toBe(true)
      await expect(row.getByRole('button', { name: 'Open in default app' })).toHaveCount(0)
      await row.getByRole('button', { name: /^More for / }).tap()
      await expect(page.getByRole('menu').getByRole('menuitem')).toHaveText([
        'Open in default app',
        'Show in Finder',
        'Copy path',
        'Download a copy',
      ])
      if (width === 390)
        await page.screenshot({ path: test.info().outputPath('files-touch-menu.png') })
      await page.getByRole('menuitem', { name: 'Open in default app' }).tap()
      await expectOpen(corpus, recording, item)
      await row.getByRole('button', { name: /^More for / }).tap()
      await expectDownload(
        page,
        corpus,
        page.getByRole('menuitem', { name: 'Download a copy' }),
        item,
        'tap',
      )
      await expect(page.getByRole('tooltip')).toHaveCount(0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      const post = await openPost(page, corpus)
      const attachment = requireFixture(post.media.find((piece) => piece.kind === 'files'))
      const card = page.locator(`[data-file-card="${attachment.id}"]`)
      await expect(card.getByRole('button', { name: /^More for / })).toBeVisible()
      await expect(card.getByRole('button', { name: 'Open in default app' })).toHaveCount(0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      const photos = await openMedia(page, corpus, 'view=images', AUTHOR)
      await page.locator(`[data-media-id="${requireFixture(photos.items[0]).id}"]`).tap()
      const dialog = page.getByRole('dialog', { name: 'Media viewer' })
      await expect(dialog.getByRole('button', { name: 'Open in default app' })).toHaveCount(0)
      await dialog.getByRole('button', { name: /^More for / }).tap()
      await expect(page.getByRole('menu').getByRole('menuitem')).toHaveText([
        'Open in default app',
        'Show in Finder',
        'Copy path',
        'Download a copy',
      ])
      if (width === 390)
        await page.screenshot({ path: test.info().outputPath('fullscreen-touch-menu.png') })
      await page.getByRole('menuitem', { name: 'Open in default app' }).tap()
      await expectOpen(corpus, recording, requireFixture(photos.items[0]))
    } finally {
      await context.close()
      runtime?.assertClean()
    }
  })
}

test('long press opens context menus on files, audio and grid tiles', async ({
  browser,
  corpus,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1024, height: 1000 },
    hasTouch: true,
  })
  let runtime: RuntimeCheck | undefined
  try {
    const page = await context.newPage()
    runtime = await watchRuntime(page, corpus)
    await capabilities(page, localCapabilities(corpus))
    for (const view of ['files', 'audio', 'images'] as const) {
      const data = await openMedia(page, corpus, `view=${view}`, AUTHOR)
      const item = requireFixture(data.items[0])
      const row = page.locator(`[data-media-id="${item.id}"]`)
      const target = view === 'audio' ? row.locator('[data-file-context]') : row
      const bounds = requireFixture(await target.boundingBox())
      const options = {
        pointerType: 'touch',
        pointerId: 7,
        isPrimary: true,
        button: 0,
        buttons: 1,
        clientX: bounds.x + 10,
        clientY: bounds.y + 10,
      }
      await target.dispatchEvent('pointerdown', options)
      await expect(page.getByRole('menu')).toBeVisible()
      await target.dispatchEvent('pointerup', { ...options, buttons: 0 })
      await expect(page.getByRole('menu').getByRole('menuitem')).toHaveText([
        'Open in default app',
        'Show in Finder',
        'Copy path',
        'Download a copy',
      ])
      await page.keyboard.press('Escape')
    }
  } finally {
    await context.close()
    runtime?.assertClean()
  }
})
