import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import type { Locator, Page } from '@playwright/test'
import type { MediaItem } from '../src/lib/api.gen'
import {
  expect,
  test,
  API_PATH,
  AUTHOR,
  GALLERY,
  REMOVED,
  inventory,
  openMedia,
  pane,
  postId,
  readyPlayer,
  scroller,
  tab,
  type MediaCorpus,
} from './media-fixtures'

function bar(page: Page): Locator {
  return page.getByRole('region', { name: 'Player', exact: true })
}

async function position(
  page: Page,
  corpus: MediaCorpus,
  item: MediaItem,
  seconds: number,
): Promise<void> {
  const response = await page.request.put(
    `${corpus.origin}${API_PATH}/media/${encodeURIComponent(item.id)}/position`,
    { data: { seconds, duration: item.duration_s } },
  )
  expect(response.ok()).toBe(true)
}

async function audioFixture(
  page: Page,
  corpus: MediaCorpus,
): Promise<{ first: MediaItem; second: MediaItem }> {
  const data = await inventory(page, corpus, 'view=audio')
  const first = data.items.find((item) => item.title === 'Track 01 A')!
  const second = data.items.find((item) => item.title === 'Track 01 B')!
  await position(page, corpus, first, 7)
  await position(page, corpus, second, 11)
  return { first, second }
}

async function start(page: Page, id: string): Promise<Locator> {
  const card = page.locator(`[data-audio-list] [data-media-id="${id}"]`)
  await card.getByRole('button', { name: /^Play / }).click()
  const audio = bar(page).locator('audio')
  await readyPlayer(audio)
  await expect.poll(() => audio.evaluate((element: HTMLMediaElement) => element.paused)).toBe(false)
  return audio
}

test('audio rows show the artist, duration and canonical played state, then replay from the start', async ({
  page,
  corpus,
}) => {
  const { first, second } = await audioFixture(page, corpus)
  await position(page, corpus, second, second.duration_s!)
  await openMedia(page, corpus, 'view=audio')
  const firstRow = page.locator(`[data-audio-list] [data-media-id="${first.id}"]`)
  const secondRow = page.locator(`[data-audio-list] [data-media-id="${second.id}"]`)
  await expect(firstRow).toContainText('Fixture orchestra')
  await expect(firstRow).toContainText('0:45')
  await expect(firstRow.locator('[title="16% played"]')).toBeVisible()
  await expect(secondRow.getByLabel('Played to the end')).toBeVisible()
  await expect(secondRow.locator('[title="100% played"]')).toBeVisible()
  const audio = await start(page, second.id)
  expect(await audio.evaluate((element: HTMLMediaElement) => element.currentTime)).toBeLessThan(3)
  await expect(secondRow.locator('[data-playing]')).toHaveCount(1)
  await bar(page).getByRole('button', { name: 'Pause', exact: true }).click()
  await expect
    .poll(
      async () =>
        (await inventory(page, corpus, 'view=audio')).items.find((item) => item.id === second.id)
          ?.finished,
    )
    .toBe(false)
})

test('one audio element keeps playing across Posts, Authors and another author', async ({
  page,
  corpus,
}) => {
  const { first } = await audioFixture(page, corpus)
  await openMedia(page, corpus, 'view=audio')
  const audio = await start(page, first.id)
  const handle = await audio.elementHandle()
  await expect(bar(page)).toContainText('Track 01 A')
  await expect(bar(page)).toContainText('Resumed at 0:07')
  const before = await audio.evaluate((element: HTMLMediaElement) => element.currentTime)
  await tab(page, 'Posts')
  await expect
    .poll(() => audio.evaluate((element: HTMLMediaElement) => element.currentTime))
    .toBeGreaterThan(before)
  await page
    .getByRole('navigation', { name: 'Library', exact: true })
    .getByRole('link', { name: 'Authors' })
    .click()
  await expect(page.getByRole('heading', { name: 'Authors', exact: true })).toBeVisible()
  await page.locator(`a[href="/a/${GALLERY}"]`).click()
  await expect(pane(page, 'posts').getByRole('heading', { level: 1 })).toHaveText('Media post 01')
  expect(
    await handle!.evaluate((element) => element === document.querySelector('audio[data-player]')),
  ).toBe(true)
  expect(await audio.evaluate((element: HTMLMediaElement) => element.paused)).toBe(false)
  await bar(page).getByRole('link', { name: 'Media post 01' }).click()
  await expect(page).toHaveURL(`${corpus.origin}/a/media_checks/p/${postId(1)}`)
  expect(new URL(page.url()).search).toBe('')
})

test('next and previous resume saved positions, ended advances and the bar controls seek and speed', async ({
  page,
  corpus,
}) => {
  const { first, second } = await audioFixture(page, corpus)
  await openMedia(page, corpus, 'view=audio')
  const audio = await start(page, first.id)
  await audio.evaluate((element: HTMLMediaElement) => {
    element.currentTime = 10
    element.pause()
  })
  await expect
    .poll(
      async () =>
        (await inventory(page, corpus, 'view=audio')).items.find((item) => item.id === first.id)
          ?.position_s,
    )
    .toBeCloseTo(10, 1)
  await bar(page).getByRole('button', { name: 'Next track' }).click()
  await expect(bar(page)).toContainText('Track 01 B')
  await readyPlayer(audio)
  await expect
    .poll(() => audio.evaluate((element: HTMLMediaElement) => element.currentTime))
    .toBeGreaterThanOrEqual(11)
  await bar(page).getByRole('button', { name: 'Previous track' }).click()
  await expect(bar(page)).toContainText('Track 01 A')
  await readyPlayer(audio)
  await expect
    .poll(() => audio.evaluate((element: HTMLMediaElement) => element.currentTime))
    .toBeGreaterThanOrEqual(10)
  await bar(page).getByRole('button', { name: 'Pause', exact: true }).click()
  await bar(page).getByRole('button', { name: 'Forward 15 seconds' }).click()
  await expect
    .poll(() => audio.evaluate((element: HTMLMediaElement) => element.currentTime))
    .toBeGreaterThanOrEqual(25)
  await bar(page).getByRole('button', { name: 'Back 15 seconds' }).click()
  await expect
    .poll(() => audio.evaluate((element: HTMLMediaElement) => element.currentTime))
    .toBeLessThan(12)
  await bar(page).getByRole('button', { name: 'Playback speed' }).click()
  expect(await audio.evaluate((element: HTMLMediaElement) => element.playbackRate)).toBe(1.25)
  await bar(page).getByRole('slider', { name: 'Position' }).focus()
  await page.keyboard.press('Home')
  await page.keyboard.press('ArrowRight')
  await expect
    .poll(() => audio.evaluate((element: HTMLMediaElement) => element.currentTime))
    .toBe(1)
  await audio.evaluate(async (element: HTMLMediaElement) => {
    element.currentTime = element.duration - 0.1
    await element.play()
  })
  await expect(bar(page)).toContainText('Track 01 B')
  await expect.poll(() => audio.evaluate((element: HTMLMediaElement) => element.paused)).toBe(false)
  expect(
    (await inventory(page, corpus, 'view=audio')).items.find((item) => item.id === second.id)
      ?.finished,
  ).toBe(false)
})

test('a broken track reports its failure and advances once to the next playable track', async ({
  page,
  corpus,
}) => {
  const { first } = await audioFixture(page, corpus)
  await page.route('**/media/**', async (route) => {
    if (decodeURIComponent(new URL(route.request().url()).pathname).endsWith(first.path))
      await route.fulfill({ status: 503, body: 'Media unavailable' })
    else await route.continue()
  })
  await openMedia(page, corpus, 'view=audio')
  await page
    .locator(`[data-media-id="${first.id}"]`)
    .getByRole('button', { name: /^Play / })
    .click()
  await expect(bar(page).getByRole('status')).toHaveText('Could not play this track.')
  await expect(bar(page)).toContainText('Track 01 B')
  const audio = bar(page).locator('audio')
  await readyPlayer(audio)
  await expect.poll(() => audio.evaluate((element: HTMLMediaElement) => element.paused)).toBe(false)
  await expect(bar(page).getByRole('status')).toHaveCount(0)
})

test('a post video pauses the bar and playing the bar pauses the post video', async ({
  page,
  corpus,
}) => {
  const { first } = await audioFixture(page, corpus)
  await openMedia(page, corpus, 'view=audio')
  const audio = await start(page, first.id)
  const audioElement = await audio.elementHandle()
  await bar(page).getByRole('link', { name: 'Media post 01' }).click()
  const video = pane(page, 'posts').locator('video').first()
  await readyPlayer(video)
  await video.evaluate(async (element: HTMLMediaElement) => {
    element.muted = true
    await element.play()
  })
  await expect.poll(() => audio.evaluate((element: HTMLMediaElement) => element.paused)).toBe(true)
  await bar(page).getByRole('button', { name: 'Play', exact: true }).click()
  await expect.poll(() => video.evaluate((element: HTMLMediaElement) => element.paused)).toBe(true)
  expect(await audio.evaluate((element: HTMLMediaElement) => element.paused)).toBe(false)
  await tab(page, 'Media')
  await pane(page, 'media')
    .getByRole('button', { name: /^Videos / })
    .click()
  await page.locator('button[data-media-id]').first().click()
  const fullscreenVideo = page.getByRole('dialog', { name: 'Media viewer' }).locator('video')
  await readyPlayer(fullscreenVideo)
  await expect
    .poll(() => fullscreenVideo.evaluate((element: HTMLMediaElement) => element.paused))
    .toBe(false)
  await expect
    .poll(() => audioElement!.evaluate((element: HTMLMediaElement) => element.paused))
    .toBe(true)
})

test('All starts its filtered audio queue and next walks from current into removed tracks', async ({
  page,
  corpus,
}) => {
  const data = await openMedia(page, corpus, 'fav=1')
  const tracks = data.items.filter((item) => item.kind === 'audio')
  const lastCurrent = tracks.findLast((item) => !item.removed)!
  const firstRemoved = tracks.find((item) => item.removed)!
  await scroller(page).evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  const tile = page.locator(`button[data-media-id="${lastCurrent.id}"]`)
  await tile.scrollIntoViewIfNeeded()
  await tile.click()
  await expect(bar(page)).toContainText(lastCurrent.title!)
  await readyPlayer(bar(page).locator('audio'))
  await bar(page).getByRole('button', { name: 'Next track' }).click()
  await expect(bar(page)).toContainText(firstRemoved.title!)
  await expect
    .poll(() =>
      bar(page)
        .locator('audio')
        .evaluate((element: HTMLMediaElement) => element.paused),
    )
    .toBe(false)
})

test('Files downloads actual bytes while a row click has no file action', async ({
  page,
  corpus,
}) => {
  const data = await openMedia(page, corpus, 'view=files')
  const item = data.items[0]!
  const row = page.locator(`[data-file-list] [data-media-id="${item.id}"]`)
  const before = page.url()
  await row.locator('[title]').first().dblclick()
  expect(page.url()).toBe(before)
  const downloading = page.waitForEvent('download')
  const link = row.getByRole('link', { name: /^Download / })
  await expect(link).toHaveAttribute('download', item.filename!)
  await link.click()
  const download = await downloading
  expect(download.suggestedFilename()).toMatch(/^Notes 01 .*\.pdf$/)
  const local = await download.path()
  expect(local).not.toBeNull()
  const downloaded = await readFile(local!)
  expect(downloaded.length).toBe(item.size)
  expect(downloaded).toEqual(await readFile(join(corpus.library, AUTHOR, item.path)))
})

for (const width of [280, 390, 820, 1440]) {
  test(`${width}px audio and Files keep controls inside the page`, async ({ page, corpus }) => {
    await page.setViewportSize({ width, height: 1000 })
    const data = await openMedia(page, corpus, 'view=audio', REMOVED)
    await start(page, data.items[0]!.id)
    await expect(bar(page)).toBeVisible()
    const bounds = await bar(page)
      .locator('button, input')
      .evaluateAll((nodes) =>
        nodes.map((node) => {
          const box = node.getBoundingClientRect()
          return { left: box.left, right: box.right, width: box.width }
        }),
      )
    expect(bounds.every((box) => box.left >= 0 && box.right <= width && box.width > 0)).toBe(true)
    await pane(page, 'media')
      .getByRole('button', { name: /^Files / })
      .click()
    await expect(page.locator('[data-file-list]')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(
      await scroller(page).evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true)
    await expect(page.locator('[data-removed-heading]')).toBeVisible()
    await expect(bar(page).locator('audio')).toHaveCount(1)
  })
}
