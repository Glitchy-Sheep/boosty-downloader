import { setTimeout as delay } from 'node:timers/promises'

import {
  expect,
  test,
  API_PATH,
  AUTHOR,
  GALLERY,
  detail,
  inventory,
  mediaPath,
  openMedia,
  pane,
  postId,
  readyPlayer,
  resetMarks,
  scroller,
  tab,
} from './media-fixtures'

test('fullscreen pushes once, steps replace, Escape focuses the last tile and Back does not reopen it', async ({
  page,
  corpus,
}) => {
  await page.goto(corpus.origin)
  await page.getByRole('link', { name: /Media Checks/ }).click()
  await tab(page, 'Media')
  const data = await inventory(page, corpus)
  const visuals = data.items.filter((item) => item.kind === 'images' || item.kind === 'videos')
  await page.locator(`[data-media-id="${visuals[0]!.id}"]`).click()
  const dialog = page.getByRole('dialog', { name: 'Media viewer' })
  await expect(dialog).toBeFocused()
  await expect(dialog).toContainText(`1 / ${visuals.length}`)
  const length = await page.evaluate(() => history.length)
  await page.keyboard.press('ArrowRight')
  await expect(dialog).toContainText(`2 / ${visuals.length}`)
  await expect(page).toHaveURL(
    new RegExp(`open=${encodeURIComponent(visuals[1]!.id).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`),
  )
  expect(await page.evaluate(() => history.length)).toBe(length)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.locator(`[data-media-id="${visuals[1]!.id}"]`)).toBeFocused()
  expect(new URL(page.url()).searchParams.has('open')).toBe(false)
  await page.goBack()
  await expect(pane(page, 'posts')).toBeVisible()
  await expect(dialog).toHaveCount(0)
  await page.goForward()
  await expect(pane(page, 'media')).toBeVisible()
  await page.goForward()
  await expect(dialog).toContainText(`2 / ${visuals.length}`)
})

test('a direct deep link closes by replacement and a distant selected tile regains focus', async ({
  page,
  corpus,
}) => {
  const data = await inventory(page, corpus, 'view=images', GALLERY)
  const distant = data.items[1400]!
  await page.goto(corpus.origin)
  await page.goto(
    `${corpus.origin}${mediaPath(GALLERY, `view=images&open=${encodeURIComponent(distant.id)}`)}`,
  )
  const dialog = page.getByRole('dialog', { name: 'Media viewer' })
  await expect(dialog).toContainText('1401 / 2000')
  await dialog.getByRole('button', { name: 'Close media viewer' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator(`[data-media-id="${distant.id}"]`)).toBeFocused()
  expect(await page.locator('[data-media-tile]').count()).toBeLessThan(200)
  expect(await scroller(page).evaluate((element) => element.scrollTop)).toBeGreaterThan(1000)
  await page.goBack()
  await expect(page).toHaveURL(`${corpus.origin}/`)
})

test('fullscreen video resumes, saves, owns its arrow keys and clears filters on its post link', async ({
  page,
  corpus,
}) => {
  const data = await inventory(page, corpus, 'view=videos')
  const item = data.items.find((piece) => piece.post_id === postId(1) && !piece.removed)!
  expect(
    (
      await page.request.put(
        `${corpus.origin}${API_PATH}/media/${encodeURIComponent(item.id)}/position`,
        { data: { seconds: 7, duration: item.duration_s } },
      )
    ).ok(),
  ).toBe(true)
  await openMedia(
    page,
    corpus,
    `view=videos&order=oldest&fav=1&open=${encodeURIComponent(item.id)}`,
  )
  const dialog = page.getByRole('dialog', { name: 'Media viewer' })
  const video = dialog.locator('video')
  await readyPlayer(video)
  await video.evaluate((element: HTMLMediaElement) => {
    element.pause()
  })
  await expect
    .poll(() => video.evaluate((element: HTMLMediaElement) => element.currentTime))
    .toBeGreaterThanOrEqual(7)
  await expect(dialog).toContainText('Resumed at 0:07')
  const address = page.url()
  await video.focus()
  await page.keyboard.press('ArrowRight')
  expect(page.url()).toBe(address)
  await dialog.getByRole('button', { name: 'Start over', exact: true }).click()
  await expect
    .poll(() => video.evaluate((element: HTMLMediaElement) => element.currentTime))
    .toBe(0)
  await expect
    .poll(
      async () =>
        (await inventory(page, corpus, 'view=videos')).items.find((piece) => piece.id === item.id)
          ?.position_s,
    )
    .toBe(0)
  await expect(dialog.getByRole('button', { name: 'Start over', exact: true })).toHaveCount(0)
  await video.evaluate((element: HTMLMediaElement) => {
    element.currentTime = 12
  })
  await expect
    .poll(
      async () =>
        (await inventory(page, corpus, 'view=videos')).items.find((piece) => piece.id === item.id)
          ?.position_s,
    )
    .toBeCloseTo(12, 1)
  await dialog.getByRole('link', { name: 'Media post 01', exact: true }).click()
  await expect(pane(page, 'posts').getByRole('heading', { level: 1 })).toHaveText('Media post 01')
  expect(new URL(page.url()).search).toBe('')
  await expect(dialog).toHaveCount(0)
  await tab(page, 'Media')
  await expect(dialog).toHaveCount(0)
})

test('direct Media favorites use shared post metadata without detail fan-out and survive reload', async ({
  page,
  corpus,
}) => {
  await resetMarks(page, corpus, 2, false)
  const details: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'GET' && /\/posts\//.test(new URL(request.url()).pathname))
      details.push(request.url())
  })
  try {
    const data = await openMedia(page, corpus, 'view=images')
    const item = data.items.find((piece) => piece.post_id === postId(2))!
    const tile = page.locator(`[data-media-tile="${item.id}"]`)
    await tile.hover()
    await tile.getByRole('button', { name: 'Add to favorites' }).click()
    await expect(tile.getByRole('button', { name: 'Remove from favorites' })).toBeEnabled()
    await expect.poll(async () => (await detail(page, corpus, 2)).favorite).toBe(true)
    expect(details).toEqual([])
    await page.reload()
    await expect(tile.getByRole('button', { name: 'Remove from favorites' })).toBeVisible()
  } finally {
    await resetMarks(page, corpus, 2)
  }
})

test('a favorite removed on Posts refreshes hidden Media before its filtered pane returns', async ({
  page,
  corpus,
}) => {
  await resetMarks(page, corpus, 2)
  try {
    const data = await openMedia(page, corpus, 'view=images&fav=1')
    const item = data.items.find((piece) => piece.post_id === postId(2))!
    await page.locator(`[data-media-id="${item.id}"]`).click()
    await page.getByRole('dialog').getByRole('link', { name: 'Media post 02', exact: true }).click()
    let held = false
    await page.route(`**/api/authors/${AUTHOR}/media*`, async (route) => {
      held = true
      await delay(450)
      await route.continue()
    })
    await page
      .getByRole('region', { name: 'Selected post' })
      .getByRole('button', { name: 'Remove from favorites', exact: true })
      .click()
    await expect.poll(async () => (await detail(page, corpus, 2)).favorite).toBe(false)
    expect(held, 'Hidden Media has no active query subscription').toBe(false)
    await page.getByRole('link', { name: 'Media', exact: true }).click()
    await expect.poll(() => held).toBe(true)
    await expect(pane(page, 'posts')).toHaveAttribute('inert', '')
    await expect(pane(page, 'media')).not.toHaveAttribute('data-shown', '')
    await expect(pane(page, 'media')).toHaveAttribute('data-shown', '')
    for (const piece of data.items.filter((candidate) => candidate.post_id === postId(2)))
      await expect(page.locator(`[data-media-id="${piece.id}"]`)).toHaveCount(0)
  } finally {
    await resetMarks(page, corpus, 2)
  }
})

test('a favorite removed in Media updates the retained filtered Posts list and counters', async ({
  page,
  corpus,
}) => {
  await resetMarks(page, corpus, 2)
  try {
    await page.goto(`${corpus.origin}/a/${AUTHOR}/p/${postId(2)}?fav=1`)
    await expect(pane(page, 'posts').getByRole('heading', { level: 1 })).toHaveText('Media post 02')
    await tab(page, 'Media')
    const item = (await inventory(page, corpus)).items.find(
      (piece) => piece.post_id === postId(2) && piece.kind === 'images',
    )!
    const tile = page.locator(`[data-media-tile="${item.id}"]`)
    await tile.hover()
    await tile.getByRole('button', { name: 'Remove from favorites' }).click()
    await expect.poll(async () => (await detail(page, corpus, 2)).favorite).toBe(false)
    await tab(page, 'Posts')
    await expect(pane(page, 'posts').locator(`[data-post-id="${postId(2)}"]`)).toHaveCount(0)
    await expect(pane(page, 'posts').getByRole('heading', { level: 1 })).toHaveText('Media post 02')
    await expect(
      page
        .getByRole('region', { name: 'Selected post' })
        .getByRole('button', { name: 'Add to favorites', exact: true }),
    ).toBeEnabled()
  } finally {
    await resetMarks(page, corpus, 2)
  }
})
