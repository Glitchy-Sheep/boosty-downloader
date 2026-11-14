import type { Locator, Page } from '@playwright/test'

import {
  API_PATH,
  POSTS,
  detail,
  expect,
  openPost,
  pane,
  readyPlayer,
  sidebar,
  storedMedia,
  test,
  type PostCorpus,
} from './post-fixtures'

async function seedPosition(
  page: Page,
  corpus: PostCorpus,
  postId: string,
  kind: 'audio' | 'videos',
  seconds: number,
): Promise<void> {
  const item = await storedMedia(page, corpus, postId, kind)
  const response = await page.request.put(
    `${corpus.origin}${API_PATH}/media/${encodeURIComponent(item.id)}/position`,
    { data: { seconds, duration: item.duration_s } },
  )
  expect(response.ok()).toBe(true)
}

async function seek(player: Locator, seconds: number): Promise<void> {
  await player.evaluate((media: HTMLMediaElement, position) => {
    media.currentTime = position
  }, seconds)
  await expect
    .poll(() => player.evaluate((media: HTMLMediaElement) => media.currentTime))
    .toBeCloseTo(seconds, 1)
}

for (const kind of ['audio', 'videos'] as const) {
  test(`${kind}: encoded media restores, persists a seek, reloads and saves Start over`, async ({
    page,
    corpus,
  }) => {
    await seedPosition(page, corpus, POSTS.playback, kind, 7)
    await openPost(page, corpus, POSTS.playback)
    const player = pane(page).locator(kind === 'audio' ? 'audio' : 'video')
    await readyPlayer(player)
    await expect
      .poll(() => player.evaluate((media: HTMLMediaElement) => media.currentTime))
      .toBeCloseTo(7, 1)
    const source = await player.evaluate((media: HTMLMediaElement) => media.currentSrc)
    expect(source).toContain('%21%27%28%29')
    expect(source).toContain('%23')
    expect(source).toContain('100%2525')
    await seek(player, 9.25)
    await expect
      .poll(async () => (await storedMedia(page, corpus, POSTS.playback, kind)).position_s)
      .toBeCloseTo(9.25, 1)
    await page.reload()
    await readyPlayer(player)
    await expect
      .poll(() => player.evaluate((media: HTMLMediaElement) => media.currentTime))
      .toBeCloseTo(9.25, 1)
    const playerCard = player.locator('..')
    await expect(playerCard).toContainText('Resumed at 0:09')
    await playerCard.getByRole('button', { name: 'Start over' }).click()
    await expect
      .poll(async () => (await storedMedia(page, corpus, POSTS.playback, kind)).position_s)
      .toBe(0)
    await page.reload()
    await readyPlayer(player)
    await expect.poll(() => player.evaluate((media: HTMLMediaElement) => media.currentTime)).toBe(0)
    await expect(player.locator('..').getByRole('button', { name: 'Start over' })).toHaveCount(0)
  })
}

test('native playback saves while playing and on post navigation without marking seen', async ({
  page,
  corpus,
}) => {
  await seedPosition(page, corpus, POSTS.boundary, 'audio', 0)
  await openPost(page, corpus, POSTS.boundary)
  const player = pane(page).locator('audio')
  await readyPlayer(player)
  await player.evaluate(async (media: HTMLMediaElement) => {
    media.muted = true
    await media.play()
  })
  await expect
    .poll(async () => (await storedMedia(page, corpus, POSTS.boundary, 'audio')).position_s, {
      timeout: 9_000,
    })
    .toBeGreaterThan(3)
  expect(await player.evaluate((media: HTMLMediaElement) => media.paused)).toBe(false)
  await player.evaluate((media: HTMLMediaElement) => {
    media.currentTime = 14
  })
  await sidebar(page).locator(`[data-post-id="${POSTS.reader}"]`).click()
  await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText('Complete saved post')
  await expect
    .poll(async () => (await storedMedia(page, corpus, POSTS.boundary, 'audio')).position_s)
    .toBeGreaterThanOrEqual(14)
  expect((await detail(page, corpus, POSTS.boundary)).seen).toBe(false)
})

test('finished media starts from zero and the final five percent is persisted as finished', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.finished)
  for (const selector of ['video', 'audio']) {
    const player = pane(page).locator(selector)
    await readyPlayer(player)
    expect(await player.evaluate((media: HTMLMediaElement) => media.currentTime)).toBe(0)
    await expect(player.locator('..').getByRole('button', { name: 'Start over' })).toHaveCount(0)
  }
  await seedPosition(page, corpus, POSTS.boundary, 'videos', 0)
  await openPost(page, corpus, POSTS.boundary)
  const video = pane(page).locator('video')
  await readyPlayer(video)
  const duration = await video.evaluate((media: HTMLMediaElement) => media.duration)
  await seek(video, duration - 0.5)
  await expect
    .poll(async () => (await storedMedia(page, corpus, POSTS.boundary, 'videos')).finished)
    .toBe(true)
  await page.reload()
  await readyPlayer(video)
  expect(await video.evaluate((media: HTMLMediaElement) => media.currentTime)).toBe(0)
})

test('a delayed save cannot overwrite a newer seek or replace the player', async ({
  page,
  corpus,
}) => {
  await seedPosition(page, corpus, POSTS.boundary, 'audio', 0)
  const item = await storedMedia(page, corpus, POSTS.boundary, 'audio')
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let intercepted = false
  await page.route(`**${API_PATH}/media/${encodeURIComponent(item.id)}/position`, async (route) => {
    if (!intercepted) {
      intercepted = true
      await gate
    }
    await route.continue()
  })
  await openPost(page, corpus, POSTS.boundary)
  const player = pane(page).locator('audio')
  await readyPlayer(player)
  const handle = await player.elementHandle()
  try {
    await seek(player, 10)
    await expect.poll(() => intercepted).toBe(true)
    await seek(player, 20)
    expect(
      await handle!.evaluate((element) => element === document.querySelector('.post-body audio')),
    ).toBe(true)
  } finally {
    release()
  }
  await expect
    .poll(async () => (await storedMedia(page, corpus, POSTS.boundary, 'audio')).position_s)
    .toBe(20)
  await page.reload()
  await readyPlayer(player)
  await expect
    .poll(() => player.evaluate((media: HTMLMediaElement) => media.currentTime))
    .toBeCloseTo(20, 1)
})

test('a rejected position write reports failure while audio keeps playing, then recovers', async ({
  page,
  corpus,
}) => {
  await seedPosition(page, corpus, POSTS.boundary, 'audio', 0)
  const item = await storedMedia(page, corpus, POSTS.boundary, 'audio')
  const endpoint = `**${API_PATH}/media/${encodeURIComponent(item.id)}/position`
  await page.route(endpoint, (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: { code: 'temporary_failure', message: 'Position write refused for the test.' },
      },
    }),
  )
  await openPost(page, corpus, POSTS.boundary)
  const player = pane(page).locator('audio')
  await readyPlayer(player)
  await player.evaluate(async (media: HTMLMediaElement) => {
    media.muted = true
    await media.play()
  })
  await expect(pane(page).getByText('Playback position could not be saved.')).toBeVisible({
    timeout: 9_000,
  })
  expect(
    await player.evaluate((media: HTMLMediaElement) => !media.paused && media.currentTime > 3),
  ).toBe(true)
  await page.unroute(endpoint)
  await player.evaluate((media: HTMLMediaElement) => media.pause())
  await expect(pane(page).getByText('Playback position could not be saved.')).toHaveCount(0)
  await expect
    .poll(async () => (await storedMedia(page, corpus, POSTS.boundary, 'audio')).position_s)
    .toBeGreaterThan(3)
})

test('returning before an in-flight save completes restores the latest local seek', async ({
  page,
  corpus,
}) => {
  await seedPosition(page, corpus, POSTS.boundary, 'audio', 7)
  const item = await storedMedia(page, corpus, POSTS.boundary, 'audio')
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let intercepted = false
  await page.route(`**${API_PATH}/media/${encodeURIComponent(item.id)}/position`, async (route) => {
    intercepted = true
    await gate
    await route.continue()
  })
  await openPost(page, corpus, POSTS.boundary)
  const player = pane(page).locator('audio')
  await readyPlayer(player)
  try {
    await seek(player, 20)
    await expect.poll(() => intercepted).toBe(true)
    await sidebar(page).locator(`[data-post-id="${POSTS.reader}"]`).click()
    await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText('Complete saved post')
    await sidebar(page).locator(`[data-post-id="${POSTS.boundary}"]`).click()
    await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText('Playback boundary')
    await readyPlayer(player)
    await expect
      .poll(() => player.evaluate((media: HTMLMediaElement) => media.currentTime))
      .toBeCloseTo(20, 1)
  } finally {
    release()
  }
  await expect
    .poll(async () => (await storedMedia(page, corpus, POSTS.boundary, 'audio')).position_s)
    .toBe(20)
})
