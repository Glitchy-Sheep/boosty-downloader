import {
  AUTHOR,
  capabilities,
  expect,
  expectOpen,
  localCapabilities,
  remoteCapabilities,
  requireFixture,
  test,
} from './file-actions-fixtures'
import { openMedia, readyPlayer } from './media-fixtures'

test('fullscreen Open pauses its video, Reveal preserves playback, and 640px folds actions', async ({
  page,
  corpus,
  recording,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openMedia(page, corpus, 'view=videos', AUTHOR)
  const item = requireFixture(data.items.find((piece) => !piece.removed))
  await page.locator(`[data-media-id="${item.id}"]`).click()
  const dialog = page.getByRole('dialog', { name: 'Media viewer' })
  const video = dialog.locator('video')
  await readyPlayer(video)
  await video.evaluate((element: HTMLVideoElement) => element.play())
  await dialog.getByRole('button', { name: 'Show in Finder' }).click()
  await expectOpen(corpus, recording, item, 'reveal')
  expect(await video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(false)
  await dialog.getByRole('button', { name: 'Open in default app' }).click()
  await expectOpen(corpus, recording, item)
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true)
  await dialog.getByRole('button', { name: /^More for / }).click()
  await expect(page.getByRole('menu').getByRole('menuitem')).toHaveText([
    'Copy path',
    'Download a copy',
  ])
  await page.keyboard.press('Escape')
  for (const width of [640, 639]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(dialog.getByRole('button', { name: 'Open in default app' })).toHaveCount(
      width < 640 ? 0 : 1,
    )
  }
  await dialog.getByRole('button', { name: /^More for / }).click()
  await expect(page.getByRole('menu').getByRole('menuitem')).toHaveText([
    'Open in default app',
    'Show in Finder',
    'Copy path',
    'Download a copy',
  ])
})

test('system failures remain accessible above the active fullscreen until dismissed', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  await page.route('**/media/*/open', (route) =>
    route.fulfill({
      status: 409,
      json: {
        error: { code: 'open_failed', message: 'No application knows how to open this file' },
      },
    }),
  )
  const data = await openMedia(page, corpus, 'view=images', AUTHOR)
  await page.locator(`[data-media-id="${requireFixture(data.items[0]).id}"]`).click()
  const dialog = page.getByRole('dialog', { name: 'Media viewer' })
  await dialog.getByRole('button', { name: 'Open in default app' }).click()
  const notice = dialog.locator('[data-file-notice]')
  await expect(notice.getByRole('alert')).toHaveText('No application knows how to open this file')
  await page.screenshot({ path: test.info().outputPath('fullscreen-error.png') })
  expect(
    await notice.evaluate((element) => Boolean(element.closest('[aria-hidden="true"], [inert]'))),
  ).toBe(false)
  await dialog.getByRole('button', { name: 'Next media' }).click()
  await expect(notice).toContainText('No application knows how to open this file')
  await notice.getByRole('button', { name: /Dismiss/ }).click()
  await expect(notice).toHaveCount(0)
})

test('audio menus and context menus pause the shared player only for Open', async ({
  page,
  corpus,
  recording,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openMedia(page, corpus, 'view=audio', AUTHOR)
  const item = requireFixture(data.items.find((piece) => !piece.removed))
  const row = page.locator(`[data-media-id="${item.id}"]`)
  await row.getByRole('button', { name: /^Play / }).click()
  const audio = page.locator('audio')
  await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.paused)).toBe(false)
  await row.getByRole('button', { name: /^More for / }).click()
  await page.getByRole('menuitem', { name: 'Show in Finder' }).click()
  await expectOpen(corpus, recording, item, 'reveal')
  expect(await audio.evaluate((element: HTMLAudioElement) => element.paused)).toBe(false)
  await row.click({ button: 'right', position: { x: 250, y: 30 } })
  await page.getByRole('menuitem', { name: 'Open in default app' }).click()
  await expectOpen(corpus, recording, item)
  await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.paused)).toBe(true)
  await row
    .getByRole('link', { name: 'File action post 1', exact: true })
    .click({ button: 'right' })
  await expect(page.getByRole('menu')).toHaveCount(0)
})

for (const view of ['images', 'videos'] as const) {
  test(`${view} tiles expose actions only in their context menu, including removed media`, async ({
    page,
    corpus,
    recording,
  }) => {
    await capabilities(page, localCapabilities(corpus))
    const data = await openMedia(page, corpus, `view=${view}`, AUTHOR)
    const item = requireFixture(data.items.find((piece) => piece.removed))
    const tile = page.locator(`[data-media-id="${item.id}"]`)
    await expect(tile.locator('[data-action]')).toHaveCount(0)
    await tile.click({ button: 'right' })
    await expect(page.getByRole('menu').getByRole('menuitem')).toHaveText([
      'Open in default app',
      'Show in Finder',
      'Copy path',
      'Download a copy',
    ])
    await page.getByRole('menuitem', { name: 'Open in default app' }).click()
    await expectOpen(corpus, recording, item)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })
}

test('remote media has download-only fullscreen and audio menus, and native context menus', async ({
  page,
  corpus,
}) => {
  await capabilities(page, remoteCapabilities())
  const photos = await openMedia(page, corpus, 'view=images', AUTHOR)
  const tile = page.locator(`[data-media-id="${requireFixture(photos.items[0]).id}"]`)
  expect(
    await tile.evaluate((element) => {
      const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
      element.dispatchEvent(event)
      return event.defaultPrevented
    }),
  ).toBe(false)
  await tile.click()
  const dialog = page.getByRole('dialog', { name: 'Media viewer' })
  await expect(dialog.getByRole('button', { name: 'Open in default app' })).toHaveCount(0)
  const more = dialog.getByRole('button', { name: /^More for / })
  if (await more.count()) await more.click()
  await expect(page.locator('[data-action="download"]:visible')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await page.keyboard.press('Escape')
  const tracks = await openMedia(page, corpus, 'view=audio', AUTHOR)
  const row = page.locator(`[data-media-id="${requireFixture(tracks.items[0]).id}"]`)
  await row.getByRole('button', { name: /^More for / }).click()
  await expect(page.getByRole('menu').getByRole('menuitem')).toHaveText(['Download a copy'])
})

test('hiding the media pane closes menus without restoring focus into hidden content', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  await openMedia(page, corpus, 'view=audio', AUTHOR)
  await page
    .getByRole('button', { name: /^More for / })
    .first()
    .click()
  await expect(page.getByRole('menu')).toBeVisible()
  await page
    .getByRole('navigation', { name: 'Author', exact: true, includeHidden: true })
    .getByRole('link', { name: 'Posts', exact: true, includeHidden: true })
    .evaluate((element: HTMLAnchorElement) => element.click())
  await expect(page.locator('.author-pane[data-tab="posts"]')).toBeVisible()
  await expect(page.getByRole('menu')).toHaveCount(0)
  expect(
    await page.evaluate(() =>
      Boolean(document.activeElement?.closest('.author-pane[data-tab="media"]')),
    ),
  ).toBe(false)
})
