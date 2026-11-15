import { setTimeout as delay } from 'node:timers/promises'

import type { Request } from '@playwright/test'

import { AUTHOR, expect, inventory, openMedia, pane, test } from './media-fixtures'

type ImageTransfer = { url: string; bytes: number; contentType: string }

const IMAGE_DRAIN_TIMEOUT_MS = 5_000

function pathComponent(value: string): string {
  return encodeURIComponent(value).replace(
    /[!'()*]/g,
    (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
  )
}

async function imageTransfer(request: Request): Promise<ImageTransfer> {
  const response = await request.response()
  if (!response) throw new Error(`Image request failed: ${request.url()}`)
  const body = await response.body()
  return {
    url: response.url(),
    bytes: body.length,
    contentType: response.headers()['content-type'] ?? '',
  }
}

async function completeImageTransfers(transfers: Promise<void>[]): Promise<void> {
  let observed: number
  do {
    observed = transfers.length
    await Promise.all(transfers)
  } while (observed !== transfers.length)
}

async function drainImageTransfers(transfers: Promise<void>[]): Promise<void> {
  const timer = new AbortController()
  try {
    await Promise.race([
      completeImageTransfers(transfers),
      delay(IMAGE_DRAIN_TIMEOUT_MS, undefined, { signal: timer.signal }).then(() => {
        throw new Error('Image transfers did not finish within the measurement window.')
      }),
    ])
  } finally {
    timer.abort()
  }
}

for (const view of ['all', 'audio'] as const) {
  test(`${view} audio artwork uses saved previews without requesting cover originals`, async ({
    page,
    corpus,
  }, info) => {
    const data = await inventory(page, corpus)
    const originalURL = (path: string): string =>
      `${corpus.origin}/media/${AUTHOR}/${path.split('/').map(pathComponent).join('/')}`
    const covers = new Set(
      Object.values(data.posts).flatMap((post) =>
        post.cover_path ? [originalURL(post.cover_path)] : [],
      ),
    )
    const tracks = new Map(
      data.items.filter((item) => item.kind === 'audio').map((item) => [item.id, item]),
    )
    const fallbacks = new Map(
      data.items
        .filter(
          (item) => item.kind === 'images' && (!item.thumb_path || item.thumb_path === item.path),
        )
        .map((item) => [item.id, originalURL(item.path)]),
    )
    const requests: string[] = []
    const images: ImageTransfer[] = []
    const transfers: Promise<void>[] = []
    const errors: string[] = []
    const measure = (request: Request): void => {
      if (request.resourceType() !== 'image') return
      requests.push(request.url())
      transfers.push(
        imageTransfer(request).then(
          (image) => {
            images.push(image)
          },
          (error: unknown) => {
            errors.push(`${request.url()}: ${String(error)}`)
          },
        ),
      )
    }
    const visibleArtwork = () =>
      pane(page, 'media')
        .locator('[data-media-id]')
        .evaluateAll((items) =>
          items.flatMap((item) => {
            const image = item.querySelector<HTMLImageElement>('[data-art] img')
            if (!image) return []
            const bounds = image.getBoundingClientRect()
            if (bounds.bottom <= 0 || bounds.top >= innerHeight) return []
            return [
              {
                id: item.getAttribute('data-media-id')!,
                url: image.currentSrc,
                complete: image.complete,
                width: image.naturalWidth,
                height: image.naturalHeight,
              },
            ]
          }),
        )
    // Capture navigation images through visible artwork readiness and the image-only drain.
    page.on('request', measure)
    try {
      await openMedia(page, corpus, `view=${view}`)
      await expect
        .poll(async () => {
          const artwork = await visibleArtwork()
          return artwork.length > 0 && artwork.every((image) => image.complete && image.width > 0)
        })
        .toBe(true)
      await drainImageTransfers(transfers)
    } finally {
      page.off('request', measure)
    }
    const artwork = await visibleArtwork()
    await info.attach(`audio-artwork-${view}.json`, {
      body: JSON.stringify({
        requestCount: requests.length,
        imageBytes: images.reduce((total, image) => total + image.bytes, 0),
        requests,
        images,
        artwork,
      }),
      contentType: 'application/json',
    })
    expect(errors).toEqual([])
    expect(images).toHaveLength(requests.length)
    expect(covers.size).toBeGreaterThan(0)
    expect(requests.filter((url) => covers.has(url))).toEqual([])
    const audioArtwork = artwork.filter((image) => tracks.has(image.id))
    expect(audioArtwork.length).toBeGreaterThan(0)
    for (const image of audioArtwork) {
      const source = `${corpus.origin}/thumbs/${AUTHOR}/${tracks.get(image.id)!.post_id}`
      expect(image.url).toBe(source)
      expect(Math.max(image.width, image.height)).toBe(480)
      expect(images).toContainEqual({
        url: source,
        bytes: expect.any(Number),
        contentType: 'image/jpeg',
      })
    }
    if (view === 'all') {
      const originalArtwork = artwork.filter((image) => fallbacks.has(image.id))
      expect(originalArtwork.length).toBeGreaterThan(0)
      for (const image of originalArtwork) {
        expect(image.url).toBe(fallbacks.get(image.id))
        expect(requests).toContain(image.url)
      }
    }
  })
}
