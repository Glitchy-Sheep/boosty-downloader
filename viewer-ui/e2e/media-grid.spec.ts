import type { Response } from '@playwright/test'

import type { MediaItem } from '../src/lib/api.gen'
import {
  expect,
  test,
  GALLERY,
  REMOVED,
  inventory,
  openMedia,
  pane,
  scroller,
} from './media-fixtures'
import { anchored, beginAnchorFrames, endAnchorFrames, firstTile } from './media-frames'
import { mediaContrast } from './media-contrast'

const VIEWS = {
  all: 'All',
  images: 'Photos',
  videos: 'Videos',
  audio: 'Audio',
  files: 'Files',
} as const

type GridRowFrame = {
  kind: 'tiles' | 'removed' | 'missing'
  firstMediaId: string | null
  top: number
  bottom: number
  height: number
  transform: string
  columns: string
}
type GridFrame = {
  time: number
  width: number
  overlaps: number
  heading: number
  rows: GridRowFrame[]
}
type ImageTransfer = { url: string; bytes: number; contentType: string }

test('all five views show canonical counts, ordering, filters and retained copies', async ({
  page,
  corpus,
}) => {
  for (const [view, label] of Object.entries(VIEWS)) {
    const data = await openMedia(page, corpus, `view=${view}`)
    await expect(
      pane(page, 'media').getByRole('button', {
        name: `${label} ${data.counts[view as keyof typeof VIEWS]}`,
        exact: true,
      }),
    ).toHaveAttribute('aria-pressed', 'true')
    const ids = await pane(page, 'media')
      .locator('[data-media-id]')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-media-id')))
    expect(ids[0]).toBe(data.items[0]!.id)
    await scroller(page).evaluate((element) => {
      element.scrollTop = element.scrollHeight
    })
    const heading = page.locator('[data-removed-heading]')
    await expect(heading).toContainText(
      `Removed by the author · ${data.items.filter((item) => item.removed).length}`,
    )
    await expect(heading).toContainText('Your copies stay on disk.')
    expect(
      await heading
        .locator(':scope > div')
        .evaluate((element) => getComputedStyle(element).borderTopWidth),
    ).toBe(view === 'files' ? '0px' : '1px')
    const missing = page.locator('[data-missing-note]')
    await missing.scrollIntoViewIfNeeded()
    expect(
      (await missing.boundingBox())!.y + (await missing.boundingBox())!.height,
    ).toBeLessThanOrEqual((await heading.boundingBox())!.y + 1)
    await expect(missing).toContainText(
      `${data.missing} more pieces of this view are not downloaded.`,
    )
    const positions = await pane(page, 'media')
      .locator('[data-media-id]')
      .evaluateAll((nodes) =>
        nodes.map((node) => ({
          id: node.getAttribute('data-media-id'),
          top: node.getBoundingClientRect().top,
        })),
      )
    const headingTop = (await heading.boundingBox())!.y
    const removedIds = new Set(data.items.filter((item) => item.removed).map((item) => item.id))
    expect(
      positions
        .filter((item) => item.top > headingTop)
        .every((item) => item.id !== null && removedIds.has(item.id)),
    ).toBe(true)
    await pane(page, 'media').getByRole('button', { name: 'Oldest first', exact: true }).click()
    await expect(page).toHaveURL(/order=oldest/)
    await expect.poll(() => scroller(page).evaluate((element) => element.scrollTop)).toBe(0)
    const oldest = await inventory(page, corpus, `view=${view}&order=oldest`)
    await expect(pane(page, 'media').locator('[data-media-id]').first()).toHaveAttribute(
      'data-media-id',
      oldest.items[0]!.id,
    )
    await pane(page, 'media').getByRole('button', { name: 'Favorites only' }).click()
    await expect(page).toHaveURL(/fav=1/)
    await pane(page, 'media').getByRole('button', { name: 'Unseen', exact: true }).click()
    await expect(page).toHaveURL(/unseen=1/)
    const filtered = await inventory(page, corpus, `view=${view}&order=oldest&fav=1&unseen=1`)
    await expect(
      pane(page, 'media').getByRole('button', {
        name: `${label} ${filtered.counts[view as keyof typeof VIEWS]}`,
        exact: true,
      }),
    ).toHaveAttribute('aria-pressed', 'true')
    expect(
      filtered.items.every((item) => !item.finished && filtered.posts[item.post_id]?.favorite),
    ).toBe(true)
    await page.reload()
    await expect(
      pane(page, 'media').getByRole('button', { name: 'Unseen', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true')
  }
})

test('two thousand photos stay virtual and the first screen transfers less than five megabytes', async ({
  page,
  corpus,
}, info) => {
  const images: ImageTransfer[] = []
  const transfers: Promise<void>[] = []
  const transferErrors: string[] = []
  const measure = (response: Response): void => {
    if (response.request().resourceType() !== 'image') return
    transfers.push(
      response.body().then(
        (body) => {
          images.push({
            url: response.url(),
            bytes: body.length,
            contentType: response.headers()['content-type'] ?? '',
          })
        },
        (error: unknown) => {
          transferErrors.push(String(error))
        },
      ),
    )
  }
  page.on('response', measure)
  const data = await openMedia(page, corpus, 'view=images', GALLERY)
  expect(data.items).toHaveLength(2000)
  await expect
    .poll(() =>
      pane(page, 'media')
        .locator('img')
        .evaluateAll((images) =>
          images
            .filter((image) => {
              const bounds = image.getBoundingClientRect()
              return bounds.bottom > 0 && bounds.top < innerHeight
            })
            .every(
              (image) =>
                image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0,
            ),
        ),
    )
    .toBe(true)
  page.off('response', measure)
  await Promise.all(transfers)
  expect(transferErrors).toEqual([])
  const thumbnailURLs = new Map(
    data.items.map((item) => [
      item.id,
      `${corpus.origin}/media/${GALLERY}/${item.thumb_path!.split('/').map(encodeURIComponent).join('/')}`,
    ]),
  )
  const visibleImages = await pane(page, 'media')
    .locator('[data-media-tile]')
    .evaluateAll((tiles) =>
      tiles.flatMap((tile) => {
        const image = tile.querySelector('img')
        if (!image || image.getBoundingClientRect().top >= innerHeight) return []
        return [
          {
            id: tile.getAttribute('data-media-tile')!,
            url: image.currentSrc,
            width: image.naturalWidth,
            height: image.naturalHeight,
          },
        ]
      }),
    )
  const imageBytes = images.reduce((total, image) => total + image.bytes, 0)
  await info.attach('media-transfer.json', {
    body: JSON.stringify({ imageBytes, images, visibleImages }),
    contentType: 'application/json',
  })
  const mediaImages = images.filter((image) => new URL(image.url).pathname.startsWith('/media/'))
  expect(mediaImages.length).toBeGreaterThan(0)
  expect(mediaImages.every((image) => image.contentType === 'image/jpeg')).toBe(true)
  expect(visibleImages.length).toBeGreaterThan(0)
  expect(visibleImages.every((image) => image.width === 480 && image.height >= 270)).toBe(true)
  for (const image of visibleImages) expect(image.url).toBe(thumbnailURLs.get(image.id))
  expect(imageBytes).toBeGreaterThan(0)
  expect(imageBytes).toBeLessThan(5_000_000)
  expect(await page.locator('[data-media-tile]').count()).toBeLessThan(200)
  await scroller(page).evaluate((element) => {
    element.scrollTop = 18_000
  })
  await expect.poll(() => firstTile(page)).not.toBe(data.items[0]!.id)
  expect(await page.locator('[data-media-tile]').count()).toBeLessThan(200)
})

test('the top tile survives six widths and every frame of three continuous drags', async ({
  page,
  corpus,
}, info) => {
  await openMedia(page, corpus, 'view=images', GALLERY)
  await scroller(page).evaluate((element) => {
    element.scrollTop = 12_000
  })
  await expect.poll(() => scroller(page).evaluate((element) => element.scrollTop)).toBe(12_000)
  const anchor = await firstTile(page)
  for (const width of [1280, 1024, 820, 1440, 390, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect.poll(() => anchored(page, anchor)).toBe(true)
  }
  await beginAnchorFrames(page, anchor)
  for (const drag of [
    { from: 1440, to: 820 },
    { from: 820, to: 1280 },
    { from: 1280, to: 390 },
  ]) {
    for (let step = 0; step <= 20; step++) {
      const width = Math.round(drag.from + ((drag.to - drag.from) * step) / 20)
      await page.setViewportSize({ width, height: 1000 })
      await page.evaluate(
        () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())),
      )
    }
  }
  const drags = await endAnchorFrames(page)
  expect(drags.length).toBeGreaterThanOrEqual(63)
  await info.attach('resize-anchors.json', {
    body: JSON.stringify({ anchor, drags }),
    contentType: 'application/json',
  })
  expect(drags.filter((frame) => !frame.anchored)).toEqual([])
})

test('equal row counts with different heading positions never overlap during view changes', async ({
  page,
  corpus,
}, info) => {
  await openMedia(page, corpus, 'view=images', 'equal_checks')
  const samples: Array<{ view: string; overlaps: number; heading: number }> = []
  for (const label of ['Videos', 'Photos', 'Videos', 'Photos']) {
    const frames = await page.evaluate(async (label) => {
      const result: GridFrame[] = []
      const button = [
        ...document.querySelectorAll<HTMLButtonElement>('[aria-label="Media views"] button'),
      ].find((element) => element.textContent?.startsWith(label))!
      const began = performance.now()
      button.click()
      await new Promise<void>((resolve) => {
        const tick = (): void => {
          const rows = [...document.querySelectorAll('[data-media-grid] > *')]
            .map((element): GridRowFrame => {
              const bounds = element.getBoundingClientRect()
              const style = getComputedStyle(element)
              const firstMediaId =
                element.querySelector<HTMLElement>('[data-media-id]')?.dataset.mediaId ?? null
              let kind: GridRowFrame['kind'] = 'missing'
              if (firstMediaId) kind = 'tiles'
              else if (element.hasAttribute('data-removed-heading')) kind = 'removed'
              return {
                kind,
                firstMediaId,
                top: bounds.top,
                bottom: bounds.bottom,
                height: bounds.height,
                transform: style.transform,
                columns: style.gridTemplateColumns,
              }
            })
            .filter((bounds) => bounds.height > 0)
            .sort((left, right) => left.top - right.top)
          result.push({
            time: performance.now() - began,
            width: document.querySelector('[data-media-grid]')!.getBoundingClientRect().width,
            rows,
            overlaps: rows.slice(1).filter((row, index) => row.top < rows[index]!.bottom - 0.5)
              .length,
            heading:
              document.querySelector('[data-removed-heading]')?.getBoundingClientRect().top ?? -1,
          })
          if (performance.now() - began < 350) requestAnimationFrame(tick)
          else resolve()
        }
        requestAnimationFrame(tick)
      })
      return result
    }, label)
    await info.attach(`equal-row-${label}-${samples.length}.json`, {
      body: JSON.stringify(frames),
      contentType: 'application/json',
    })
    expect(frames.every((frame) => frame.overlaps === 0)).toBe(true)
    samples.push({ view: label, ...frames.at(-1)! })
  }
  expect(samples[0]!.heading).not.toBe(samples[1]!.heading)
  await info.attach('equal-row-frames.json', {
    body: JSON.stringify(samples),
    contentType: 'application/json',
  })
})

for (const theme of ['dark', 'light'] as const) {
  test(`${theme}: All audio titles remain readable even over a white cover`, async ({
    page,
    corpus,
  }, info) => {
    await page.emulateMedia({ colorScheme: theme })
    await openMedia(page, corpus)
    const readings = await mediaContrast(page)
    expect(readings.length).toBeGreaterThan(0)
    expect(readings.filter((reading) => reading.ratio < 4.5)).toEqual([])
    await info.attach(`media-all-${theme}.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
  })

  test(`${theme}: removed-only views start at their heading and keep names readable`, async ({
    page,
    corpus,
  }, info) => {
    await page.emulateMedia({ colorScheme: theme })
    for (const view of Object.keys(VIEWS)) {
      await openMedia(page, corpus, `view=${view}`, REMOVED)
      const heading = page.locator('[data-removed-heading]')
      await expect(heading).toBeVisible()
      const position = await heading.evaluate((element) => ({
        top:
          element.querySelector('h2')!.getBoundingClientRect().top -
          element.parentElement!.getBoundingClientRect().top,
        rule: getComputedStyle(element.firstElementChild!).borderTopWidth,
      }))
      expect(position.top).toBeLessThanOrEqual(20)
      expect(position.rule).toBe('0px')
      await expect(page.locator('[data-missing-note]')).toHaveCount(0)
      const art = page.locator('[data-art]').first()
      await page.mouse.move(0, 0)
      expect(
        Number(await art.evaluate((element) => getComputedStyle(element).opacity)),
      ).toBeLessThan(1)
      const row = page.locator('[data-media-id]').first()
      expect(await row.ariaSnapshot()).toContain('removed by the author')
      await row.hover()
      await expect
        .poll(() => art.evaluate((element) => Number(getComputedStyle(element).opacity)))
        .toBe(1)
      await page.mouse.move(0, 0)
      if (view === 'audio' || view === 'files') await row.locator('button, a').first().focus()
      else await row.focus()
      await expect
        .poll(() => art.evaluate((element) => Number(getComputedStyle(element).opacity)))
        .toBe(1)
      if (view === 'audio' || view === 'files') {
        const contrast = await mediaContrast(page)
        expect(contrast.length).toBeGreaterThan(0)
        expect(contrast.filter((reading) => reading.ratio < 4.5)).toEqual([])
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
    }
    await page.setViewportSize({ width: 390, height: 1000 })
    await info.attach(`media-files-${theme}-390.png`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
  })
}

test('removed videos without previews keep their normal controls and a visibly dimmed stand-in', async ({
  page,
  corpus,
}) => {
  const data = await openMedia(page, corpus, 'view=videos')
  const removed = data.items.find((item) => item.removed)!
  const kept = data.items.find((item) => !item.removed)!
  const tile = (item: MediaItem) => page.locator(`[data-media-tile="${item.id}"]`)
  await tile(removed).scrollIntoViewIfNeeded()
  await page.mouse.move(0, 0)
  expect(removed.thumb_path).toBeNull()
  expect(kept.thumb_path).toBeNull()
  expect(
    Number(
      await tile(removed)
        .locator('[data-art]')
        .evaluate((element) => getComputedStyle(element).opacity),
    ),
  ).toBe(0.7)
  await tile(removed).locator('button[data-media-id]').click()
  await expect(page.getByRole('dialog')).toContainText('Removed by the author')
  await expect(page.getByRole('dialog').locator('video')).toBeVisible()
})

test('retained media of a locked post offers viewing without editable hearts', async ({
  page,
  corpus,
}) => {
  const data = await openMedia(page, corpus, 'view=images')
  const item = data.items.find((piece) => data.posts[piece.post_id]?.access === 'locked')!
  const tile = page.locator(`[data-media-tile="${item.id}"]`)
  await tile.hover()
  await expect(tile.getByRole('button', { name: /favorites/ })).toHaveCount(0)
  await tile.locator('button[data-media-id]').click()
  await expect(page.getByRole('dialog', { name: 'Media viewer' })).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('button', { name: /favorites/ })).toHaveCount(0)
})

test.describe('touch media', () => {
  test.use({ hasTouch: true })
  test('removed pictures stay dimmed and hearts remain reachable without hover', async ({
    page,
    corpus,
  }) => {
    await page.setViewportSize({ width: 390, height: 1000 })
    await openMedia(page, corpus, 'view=images', REMOVED)
    expect(await page.evaluate(() => matchMedia('(hover: none)').matches)).toBe(true)
    const tile = page.locator('[data-media-tile]').first()
    expect(
      Number(
        await tile.locator('[data-art]').evaluate((element) => getComputedStyle(element).opacity),
      ),
    ).toBe(0.7)
    const heart = tile.getByRole('button', { name: /favorites/ })
    await expect(heart).toBeVisible()
    expect(
      await heart.evaluate((element) => {
        let alpha = 1
        for (let node: Element | null = element; node; node = node.parentElement)
          alpha *= Number(getComputedStyle(node).opacity)
        return alpha
      }),
    ).toBe(1)
  })
})
