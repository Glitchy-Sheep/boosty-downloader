import { setTimeout as delay } from 'node:timers/promises'

import type { Page, TestInfo } from '@playwright/test'

import {
  expect,
  test,
  AUTHOR,
  GALLERY,
  detail,
  mediaPath,
  openMedia,
  openPost,
  pane,
  postPath,
  readyPlayer,
  scroller,
  tab,
} from './media-fixtures'
import {
  switchFrames,
  verifySwitch,
  type SwitchCaptureWindow,
  type SwitchFrame,
  type TabAction,
} from './media-frames'
import { requireFixture } from './required-fixture'

// Measure frames without concurrent DOM capture or screencast encoding.
test.use({ trace: 'off' })

test('tabs retain the same DOM, post/list/grid scroll and independent filters through Back and Forward', async ({
  page,
  corpus,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 800 })
  await openPost(page, corpus, 6, 'kind=videos')
  const article = await pane(page, 'posts').locator('article').elementHandle()
  const postScroller = page.getByRole('region', { name: 'Selected post' })
  const listScroller = page.locator('[data-post-list]')
  await postScroller.evaluate((element) => {
    element.scrollTop = 400
  })
  await listScroller.evaluate((element) => {
    element.scrollTop = 90
  })
  const before = {
    post: await postScroller.evaluate((element) => element.scrollTop),
    list: await listScroller.evaluate((element) => element.scrollTop),
  }
  expect(before.post).toBeGreaterThan(0)
  expect(before.list).toBeGreaterThan(0)
  const first = await recordSwitch(page, 'media', info, 'tab-first')
  verifySwitch(first, 'media')
  const photos = pane(page, 'media').getByRole('button', { name: /^Photos / })
  await photos.click()
  await expect(page).toHaveURL(/view=images/)
  await expect(photos).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('status', { name: 'Updating media' })).toHaveCount(0)
  const unseen = pane(page, 'media').getByRole('button', { name: 'Unseen', exact: true })
  await unseen.click()
  await expect(page).toHaveURL(/unseen=1/)
  await expect(unseen).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('status', { name: 'Updating media' })).toHaveCount(0)
  await scroller(page).evaluate((element) => {
    element.scrollTop = 370
  })
  const mediaTop = await scroller(page).evaluate((element) => element.scrollTop)
  expect(mediaTop).toBeGreaterThan(0)
  const mediaAddress = page.url()
  const grid = await page.locator('[data-media-grid]').elementHandle()
  await expect
    .poll(() =>
      pane(page, 'media')
        .locator('img')
        .evaluateAll((images) =>
          images
            .filter((image) => {
              const r = image.getBoundingClientRect()
              return r.bottom > 0 && r.top < innerHeight
            })
            .every(
              (image) =>
                image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0,
            ),
        ),
    )
    .toBe(true)
  const back = await recordSwitch(page, 'posts', info, 'tab-return')
  verifySwitch(back, 'posts')
  expect(page.url()).toBe(`${corpus.origin}${postPath(6, 'kind=videos')}`)
  expect(
    await article!.evaluate(
      (element) => element === document.querySelector('.author-pane[data-tab="posts"] article'),
    ),
  ).toBe(true)
  expect(await postScroller.evaluate((element) => element.scrollTop)).toBe(before.post)
  expect(await listScroller.evaluate((element) => element.scrollTop)).toBe(before.list)
  expect(back.every((frame) => frame.articleOpacity === 1)).toBe(true)
  const again = await recordSwitch(page, 'media', info, 'tab-media-again')
  verifySwitch(again, 'media')
  expect(page.url()).toBe(mediaAddress)
  expect(await scroller(page).evaluate((element) => element.scrollTop)).toBe(mediaTop)
  expect(
    await grid!.evaluate((element) => element === document.querySelector('[data-media-grid]')),
  ).toBe(true)
  expect(
    await pane(page, 'media')
      .locator('img')
      .evaluateAll((images) =>
        images
          .filter((image) => {
            const r = image.getBoundingClientRect()
            return r.bottom > 0 && r.top < innerHeight
          })
          .every(
            (image) =>
              image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0,
          ),
      ),
  ).toBe(true)
  verifySwitch(await recordSwitch(page, 'back', info, 'tab-history-back'), 'posts')
  verifySwitch(await recordSwitch(page, 'forward', info, 'tab-history-forward'), 'media')
  await info.attach('tab-frames.json', {
    body: JSON.stringify({ first, back, again }),
    contentType: 'application/json',
  })
})

test('direct Media entry opens the newest post without moving the header or leaking filters', async ({
  page,
  corpus,
}) => {
  await openMedia(page, corpus, 'view=images&unseen=1&fav=1&order=oldest')
  const logo = await page.getByRole('link', { name: 'Boosty Library' }).boundingBox()
  await tab(page, 'Posts')
  await expect(page).toHaveURL(`${corpus.origin}${postPath()}`)
  await expect(pane(page, 'posts').getByRole('heading', { level: 1 })).toHaveText('Media post 01')
  expect(await page.getByRole('link', { name: 'Boosty Library' }).boundingBox()).toEqual(logo)
})

test('slow Media moves its pill immediately and disables the outgoing post before the response', async ({
  page,
  corpus,
}, info) => {
  await openPost(page, corpus)
  const marks = await detail(page, corpus)
  let requested = false
  await page.route(`**/api/authors/${AUTHOR}/media*`, async (route) => {
    requested = true
    await delay(650)
    await route.continue()
  })
  const recording = recordSwitch(page, 'media', info, 'slow-tab', { duration: 1100 })
  await expect.poll(() => requested).toBe(true)
  await expect(pane(page, 'posts')).toHaveAttribute('inert', '')
  const text = await pane(page, 'posts').innerText()
  expect(text).toContain('Media post 01')
  await page.keyboard.press('j')
  await page.keyboard.press('s')
  await page.keyboard.press('f')
  await page.keyboard.press('/')
  await page.keyboard.press('[')
  const frames = await recording
  verifySwitch(frames, 'media')
  const settledPill = frames.at(-1)!.pill
  expect(frames.find((frame) => Math.abs(frame.pill - settledPill) < 0.1)!.time).toBeLessThan(400)
  expect(
    frames.find((frame) => frame.panes.some((part) => part.tab === 'media'))!.time,
  ).toBeGreaterThanOrEqual(600)
  expect(new URL(page.url()).pathname).toBe(mediaPath())
  const after = await detail(page, corpus)
  expect({ seen: after.seen, favorite: after.favorite }).toEqual({
    seen: marks.seen,
    favorite: marks.favorite,
  })
  expect(
    await page.evaluate(
      () => document.activeElement?.closest('.author-pane[data-tab="posts"]') !== null,
    ),
  ).toBe(false)
})

test('hidden post players pause, shortcuts stay quiet and a search draft resumes only on return', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus)
  const video = pane(page, 'posts').locator('video').first()
  await readyPlayer(video)
  await video.evaluate(async (element: HTMLMediaElement) => {
    element.muted = true
    await element.play()
  })
  const search = page.getByRole('textbox', { name: 'Search posts' })
  await search.fill('needle draft')
  await tab(page, 'Media')
  await expect.poll(() => video.evaluate((element: HTMLMediaElement) => element.paused)).toBe(true)
  const address = page.url()
  for (const key of ['j', 's', 'f', '/', '[']) await page.keyboard.press(key)
  await delay(300)
  expect(page.url()).toBe(address)
  expect(new URL(address).searchParams.has('q')).toBe(false)
  await tab(page, 'Posts')
  await expect(search).toHaveValue('needle draft')
  await expect(page).toHaveURL(/q=needle(?:\+|%20)draft/)
  expect(await video.evaluate((element: HTMLMediaElement) => element.paused)).toBe(true)
})

test('hidden image and bulk portals close even when history leaves their tab', async ({
  page,
  corpus,
}) => {
  await openMedia(page, corpus)
  await tab(page, 'Posts')
  const photo = pane(page, 'posts').locator('.post-body img').first()
  await photo.click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.goBack()
  await expect(pane(page, 'media')).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await tab(page, 'Posts')
  await page.getByRole('button', { name: 'Mark posts', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Mark all as seen', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.goBack()
  await expect(pane(page, 'media')).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(
    await page.evaluate(
      () => document.activeElement?.closest('.author-pane[data-tab="posts"]') !== null,
    ),
  ).toBe(false)
})

for (const state of ['error', 'empty'] as const) {
  test(`${state} post content remains during exit and returns intact`, async ({
    page,
    corpus,
  }, info) => {
    if (state === 'error') {
      await page.goto(`${corpus.origin}/a/${AUTHOR}/p/missing`)
      await expect(pane(page, 'posts').getByRole('alert')).toBeVisible()
    } else {
      await page.goto(`${corpus.origin}/a/${AUTHOR}?q=no-such-phrase`)
      await expect(pane(page, 'posts')).toContainText('No posts match these filters.')
    }
    const text = await page.getByRole('region', { name: 'Selected post' }).textContent()
    const exit = await recordSwitch(page, 'media', info, `${state}-exit`)
    verifySwitch(exit, 'media')
    expect(exit.every((frame) => frame.textLength === text!.length)).toBe(true)
    verifySwitch(await recordSwitch(page, 'posts', info, `${state}-return`), 'posts')
    expect(await page.getByRole('region', { name: 'Selected post' }).textContent()).toBe(text)
  })
}

test('reduced motion reveals the destination in one frame and new author discards retained places', async ({
  page,
  corpus,
}, info) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await openPost(page, corpus)
  const responseDelay = 300
  await page.route(`**/api/authors/${AUTHOR}/media*`, async (route) => {
    await delay(responseDelay)
    await route.continue()
  })
  const frames = await recordSwitch(page, 'media', info, 'reduced-motion', {
    duration: 5_000,
    firstMountedPane: 'media',
  })
  const appeared = requireFixture(
    frames.find((frame) => frame.panes.some((part) => part.tab === 'media')),
  )
  expect(appeared.time).toBeGreaterThanOrEqual(responseDelay)
  expect(appeared.panes.find((part) => part.tab === 'media')).toMatchObject({
    opacity: 1,
    x: 0,
    visible: true,
  })
  expect(appeared.panes.find((part) => part.tab === 'posts')?.visible).toBe(false)
  await page.goto(`${corpus.origin}${mediaPath(GALLERY, 'view=images')}`)
  await expect(pane(page, 'media')).toBeVisible()
  expect(await pane(page, 'posts').count()).toBe(0)
})

async function recordSwitch(
  page: Page,
  action: TabAction,
  info: TestInfo,
  name: string,
  capture: SwitchCaptureWindow = {},
): Promise<SwitchFrame[]> {
  const { frames, diagnostics } = await switchFrames(page, action, capture)
  await info.attach(`${name}-frames.json`, {
    body: JSON.stringify(frames),
    contentType: 'application/json',
  })
  await info.attach(`${name}-performance.json`, {
    body: JSON.stringify(diagnostics),
    contentType: 'application/json',
  })
  return frames
}
