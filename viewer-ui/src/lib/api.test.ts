import { afterEach, assert, expect, test, vi } from 'vitest'

import {
  ApiError,
  getAuthor,
  getAuthors,
  getMedia,
  getPost,
  getPosts,
  getTags,
  getMarksProgress,
  savePlaybackPosition,
  setFavorite,
  setSeen,
  setSeenMany,
} from '@/lib/api'
import { toPostFilters, type Filters } from '@/lib/filters'
import { savedMediaPage } from '@/test/media-fixtures'

afterEach(() => vi.unstubAllGlobals())

test('loads typed media with only its normalized filters and forwards cancellation', async () => {
  const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json(savedMediaPage))
  vi.stubGlobal('fetch', request)
  const controller = new AbortController()
  expect(
    await getMedia(
      'студия +',
      { view: 'videos', order: 'oldest', unseen: 1, fav: 1, open: 'piece' },
      controller.signal,
    ),
  ).toEqual(savedMediaPage)
  expect(request).toHaveBeenCalledWith(
    '/api/authors/%D1%81%D1%82%D1%83%D0%B4%D0%B8%D1%8F%20%2B/media?view=videos&order=oldest&unseen=1&fav=1',
    {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    },
  )
  request.mockResolvedValueOnce(Response.json(savedMediaPage))
  await getMedia('studio', {})
  expect(request).toHaveBeenLastCalledWith('/api/authors/studio/media', {
    headers: { Accept: 'application/json' },
    signal: null,
  })
})

test('loads the same-origin authors contract and forwards cancellation', async () => {
  const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json([]))
  vi.stubGlobal('fetch', request)
  const controller = new AbortController()

  expect(await getAuthors(controller.signal)).toEqual([])
  expect(request).toHaveBeenCalledWith('/api/authors', {
    headers: { Accept: 'application/json' },
    signal: controller.signal,
  })
})

test('preserves the structured API error status, code and useful message', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(
        {
          error: { code: 'library_unavailable', message: 'The library is unavailable.' },
        },
        { status: 409 },
      ),
    ),
  )

  await expect(getAuthors()).rejects.toMatchObject({
    name: 'ApiError',
    status: 409,
    code: 'library_unavailable',
    message: 'The library is unavailable.',
  })
})

test.each(['<html>Gateway failure</html>', JSON.stringify({ error: '<script>unsafe</script>' })])(
  'uses a plain fallback for an unexpected HTTP error body',
  async (body) => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(new Response(body, { status: 502 })),
    )

    await expect(getAuthors()).rejects.toEqual(
      new ApiError(502, 'The library request failed (502).'),
    )
  },
)

test('does not translate a cancelled request into an API error', async () => {
  const aborted = new DOMException('Aborted', 'AbortError')
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockRejectedValue(aborted))

  await expect(getAuthors()).rejects.toBe(aborted)
})

test('preserves cancellation while reading an HTTP error response body', async () => {
  const controller = new AbortController()
  const response = new Response('', { status: 409 })
  const reason = new DOMException('Left the page', 'AbortError')
  vi.spyOn(response, 'json').mockImplementation(async () => {
    controller.abort(reason)
    throw reason
  })
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(response))

  await expect(getAuthors(controller.signal)).rejects.toBe(reason)
})

test('keeps all post filters and literal search text in the API request', async () => {
  const result = { rows: [], months: [], total: 0 }
  const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json(result))
  vi.stubGlobal('fetch', request)
  const controller = new AbortController()
  const filters: Filters = {
    q: '001.0 + %',
    tag: 'null',
    kind: 'images',
    unseen: 1,
    fav: 1,
    locked: 1,
    incomplete: 1,
    order: 'oldest',
  }

  expect(await getPosts('author-name', filters, controller.signal)).toEqual(result)
  const call = request.mock.calls[0]
  assert.isDefined(call)
  const [input, options] = call
  assert(typeof input === 'string')
  const url = new URL(input, 'http://localhost')
  expect(url.pathname).toBe('/api/authors/author-name/posts')
  expect(Object.fromEntries(url.searchParams)).toEqual({
    q: '001.0 + %',
    tag: 'null',
    kind: 'images',
    unseen: '1',
    fav: '1',
    locked: '1',
    incomplete: '1',
    order: 'oldest',
  })
  expect(options?.signal).toBe(controller.signal)
})

test('encodes resource identities once and keeps detail independent of filters', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async () => Response.json({}))
  vi.stubGlobal('fetch', request)

  await getAuthor('автор %2F')
  await getTags('автор %2F')
  await getPost('автор %2F', 'post #?%')

  const author = '/api/authors/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%252F'
  expect(request.mock.calls.map((call) => call[0])).toEqual([
    author,
    `${author}/tags`,
    `${author}/posts/post%20%23%3F%25`,
  ])
})

test('writes favorite and opaque media positions to their actual endpoints', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async () => Response.json({}))
  vi.stubGlobal('fetch', request)

  await setFavorite('автор %', 'post #', true)
  await savePlaybackPosition('автор %', 'opaque/%2F', { seconds: 3, duration: 20 }, true)

  const authorPath = '/api/authors/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%25'
  expect(request.mock.calls).toEqual([
    [
      `${authorPath}/posts/post%20%23/marks`,
      {
        method: 'PUT',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: '{"favorite":true}',
        keepalive: false,
      },
    ],
    [
      `${authorPath}/media/opaque%2F%252F/position`,
      {
        method: 'PUT',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: '{"seconds":3,"duration":20}',
        keepalive: true,
      },
    ],
  ])
})

test.each([NaN, Infinity, -1])(
  'rejects invalid playback values before JSON can convert %s to null',
  async (value) => {
    const request = vi.fn<typeof fetch>()
    vi.stubGlobal('fetch', request)
    await expect(
      savePlaybackPosition('studio', 'media', { seconds: value, duration: 100 }, false),
    ).rejects.toThrow('finite')
    await expect(
      savePlaybackPosition('studio', 'media', { seconds: 0, duration: value }, false),
    ).rejects.toThrow('finite')
    expect(request).not.toHaveBeenCalled()
  },
)

test('reports rejected writes as structured errors', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(
        {
          error: { code: 'write_refused', message: 'The library is read-only.' },
        },
        { status: 403 },
      ),
    ),
  )
  await expect(setFavorite('studio', 'post', true)).rejects.toMatchObject({
    status: 403,
    code: 'write_refused',
  })
})

test('writes one seen field and a normalized filtered bulk request to their endpoints', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async () => Response.json({ count: 3 }))
  vi.stubGlobal('fetch', request)
  const filters = toPostFilters({ q: '001 + %', tag: 'null', unseen: 1, fav: 1, order: 'oldest' })
  await setSeen('автор %', 'post #', true)
  expect(await setSeenMany('автор %', { filters, seen: false })).toEqual({ count: 3 })
  const author = '/api/authors/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%25'
  expect(request.mock.calls).toEqual([
    [
      `${author}/posts/post%20%23/marks`,
      {
        method: 'PUT',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: '{"seen":true}',
        keepalive: false,
      },
    ],
    [
      `${author}/marks`,
      {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ filters, seen: false }),
        keepalive: false,
      },
    ],
  ])
})

test('loads numerical bulk progress with caller-owned cancellation', async () => {
  const result = { active: true, total: 12, completed: 8, changed: 3 }
  const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json(result))
  vi.stubGlobal('fetch', request)
  const controller = new AbortController()
  expect(await getMarksProgress('writer', controller.signal)).toEqual(result)
  expect(request).toHaveBeenCalledExactlyOnceWith('/api/authors/writer/marks/progress', {
    headers: { Accept: 'application/json' },
    signal: controller.signal,
  })
})

test('preserves the bulk conflict response rather than reporting zero changes', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        Response.json(
          { error: { code: 'bulk_busy', message: 'Another operation is running.' } },
          { status: 409 },
        ),
      ),
  )
  await expect(
    setSeenMany('writer', { filters: toPostFilters({}), seen: true }),
  ).rejects.toMatchObject({
    status: 409,
    code: 'bulk_busy',
    message: 'Another operation is running.',
  })
})
