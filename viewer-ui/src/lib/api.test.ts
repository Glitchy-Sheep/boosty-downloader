import { afterEach, expect, test, vi } from 'vitest'

import { ApiError, getAuthors } from '@/lib/api'

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
