import { afterEach, expect, test, vi } from 'vitest'

import { ApiError, getAuthor, getAuthors, getPost, getPosts, getTags, savePlaybackPosition, setFavorite } from '@/lib/api'
import type { Filters } from '@/lib/filters'

afterEach(() => vi.unstubAllGlobals())

test('loads the same-origin authors contract and forwards cancellation', async () => {
  const request = vi.fn().mockResolvedValue(Response.json([]))
  vi.stubGlobal('fetch', request)
  const controller = new AbortController()

  expect(await getAuthors(controller.signal)).toEqual([])
  expect(request).toHaveBeenCalledWith('/api/authors', {
    headers: { Accept: 'application/json' }, signal: controller.signal,
  })
})

test('preserves the structured API error status, code and useful message', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
    error: { code: 'library_unavailable', message: 'The library is unavailable.' },
  }, { status: 409 })))

  await expect(getAuthors()).rejects.toMatchObject({
    name: 'ApiError', status: 409, code: 'library_unavailable', message: 'The library is unavailable.',
  })
})

test.each(['<html>Gateway failure</html>', JSON.stringify({ error: '<script>unsafe</script>' })])(
  'uses a plain fallback for an unexpected HTTP error body', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 502 })))

    await expect(getAuthors()).rejects.toEqual(new ApiError(502, 'The library request failed (502).'))
  },
)

test('does not translate a cancelled request into an API error', async () => {
  const aborted = new DOMException('Aborted', 'AbortError')
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(aborted))

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
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

  await expect(getAuthors(controller.signal)).rejects.toBe(reason)
})

test('keeps all post filters and literal search text in the API request', async () => {
  const result = { rows: [], months: [], total: 0 }
  const request = vi.fn().mockResolvedValue(Response.json(result))
  vi.stubGlobal('fetch', request)
  const controller = new AbortController()
  const filters: Filters = { q: '001.0 + %', tag: 'null', kind: 'images', unseen: 1, fav: 1, locked: 1, incomplete: 1, order: 'oldest' }

  expect(await getPosts('author-name', filters, controller.signal)).toEqual(result)
  const url = new URL(request.mock.calls[0][0], 'http://localhost')
  expect(url.pathname).toBe('/api/authors/author-name/posts')
  expect(Object.fromEntries(url.searchParams)).toEqual({
    q: '001.0 + %', tag: 'null', kind: 'images', unseen: '1', fav: '1', locked: '1', incomplete: '1', order: 'oldest',
  })
  expect(request.mock.calls[0][1].signal).toBe(controller.signal)
})

test('encodes resource identities once and keeps detail independent of filters', async () => {
  const request = vi.fn().mockImplementation(async () => Response.json({}))
  vi.stubGlobal('fetch', request)

  await getAuthor('автор %2F')
  await getTags('автор %2F')
  await getPost('автор %2F', 'post #?%')

  const author = '/api/authors/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%252F'
  expect(request.mock.calls.map(call => call[0])).toEqual([
    author, `${author}/tags`, `${author}/posts/post%20%23%3F%25`,
  ])
})

test('writes favorite and opaque media positions to their actual endpoints', async () => {
  const request = vi.fn().mockImplementation(async () => Response.json({}))
  vi.stubGlobal('fetch', request)

  await setFavorite('автор %', 'post #', true)
  await savePlaybackPosition('автор %', 'opaque/%2F', { seconds: 3, duration: 20 }, true)

  const authorPath = '/api/authors/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%25'
  expect(request.mock.calls).toEqual([
    [`${authorPath}/posts/post%20%23/marks`, {
      method: 'PUT', headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: '{"favorite":true}', keepalive: false,
    }],
    [`${authorPath}/media/opaque%2F%252F/position`, {
      method: 'PUT', headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: '{"seconds":3,"duration":20}', keepalive: true,
    }],
  ])
})

test.each([NaN, Infinity, -1])('rejects invalid playback values before JSON can convert %s to null', async value => {
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  await expect(savePlaybackPosition('studio', 'media', { seconds: value, duration: 100 }, false)).rejects.toThrow('finite')
  await expect(savePlaybackPosition('studio', 'media', { seconds: 0, duration: value }, false)).rejects.toThrow('finite')
  expect(request).not.toHaveBeenCalled()
})

test('reports rejected writes as structured errors', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
    error: { code: 'write_refused', message: 'The library is read-only.' },
  }, { status: 403 })))
  await expect(setFavorite('studio', 'post', true)).rejects.toMatchObject({ status: 403, code: 'write_refused' })
})
