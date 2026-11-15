import { afterEach, expect, test, vi } from 'vitest'
import { QueryObserver } from '@tanstack/react-query'

import { saveMediaPosition } from '@/lib/playback-mutations'
import { createQueryClient, mediaQuery, postQuery } from '@/lib/queries'
import { savedMediaPage } from '@/test/media-fixtures'
import { savedPost, savedVideo } from '@/test/post-fixtures'

afterEach(() => vi.unstubAllGlobals())

function deferredResponse() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

test.each(['post', 'media'] as const)(
  'a late initial %s load cannot replace a saved playback position',
  async (kind) => {
    const write = deferredResponse()
    const first = deferredResponse()
    const saved = { ...savedVideo, position_s: 80 }
    let writes = 0
    let reads = 0
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
        if (init?.method === 'PUT') {
          writes++
          return write.promise
        }
        if (++reads === 1) return first.promise
        return Response.json(
          kind === 'post'
            ? { ...savedPost, media: [saved] }
            : { ...savedMediaPage, items: [saved] },
        )
      }),
    )
    const client = createQueryClient()
    const saving = saveMediaPosition(
      client,
      'studio',
      savedPost.id,
      savedVideo,
      { seconds: 80, duration: 100 },
      false,
    )
    await vi.waitFor(() => expect(writes).toBe(1))
    const loader =
      kind === 'post'
        ? client.ensureQueryData(postQuery('studio', savedPost.id)).then((post) => post.media)
        : client.ensureQueryData(mediaQuery('studio', {})).then((page) => page.items)
    await vi.waitFor(() => expect(reads).toBe(1))
    write.resolve(Response.json(saved))
    await vi.waitFor(() =>
      expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
        phase: 'refreshing',
      }),
    )
    first.resolve(Response.json(kind === 'post' ? savedPost : savedMediaPage))
    await saving
    await expect(loader).resolves.toMatchObject([{ position_s: 80 }])
    await vi.waitFor(() => expect(client.isMutating()).toBe(0))
    expect(reads).toBe(3)
    client.clear()
  },
)

test('an already running Media loader survives a playback write and returns its saved position', async () => {
  const write = deferredResponse()
  const first = deferredResponse()
  const saved = { ...savedVideo, position_s: 80 }
  let reads = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
      if (init?.method === 'PUT') return write.promise
      return ++reads === 1 ? first.promise : Response.json({ ...savedMediaPage, items: [saved] })
    }),
  )
  const client = createQueryClient()
  const loader = client.ensureQueryData(mediaQuery('studio', {}))
  const fulfilled = expect(loader).resolves.toMatchObject({ items: [{ position_s: 80 }] })
  await vi.waitFor(() => expect(reads).toBe(1))
  const saving = saveMediaPosition(
    client,
    'studio',
    savedPost.id,
    savedVideo,
    { seconds: 80, duration: 100 },
    false,
  )
  write.resolve(Response.json(saved))
  await vi.waitFor(() =>
    expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
      phase: 'refreshing',
    }),
  )
  first.resolve(Response.json(savedMediaPage))
  await saving
  await fulfilled
  await vi.waitFor(() => expect(client.isMutating()).toBe(0))
  expect(reads).toBe(3)
  client.clear()
})

test('ordinary position saves update active Media without refetching the full inventory', async () => {
  const saved = { ...savedVideo, position_s: 45 }
  const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json(saved))
  vi.stubGlobal('fetch', request)
  const client = createQueryClient()
  const query = mediaQuery('studio', {})
  client.setQueryData(query.queryKey, savedMediaPage)
  const observer = new QueryObserver(client, query)
  const unsubscribe = observer.subscribe(() => {})
  const response = await saveMediaPosition(
    client,
    'studio',
    savedPost.id,
    savedVideo,
    { seconds: 45, duration: 100 },
    true,
  )
  expect(response).toEqual(saved)
  expect(request).toHaveBeenCalledOnce()
  expect(request.mock.calls[0]?.[1]).toMatchObject({ method: 'PUT', keepalive: true })
  expect(client.getQueryData(query.queryKey)?.items[0]?.position_s).toBe(45)
  expect(client.getQueryState(query.queryKey)?.isInvalidated).toBe(false)
  unsubscribe()
  client.clear()
})

test('a failed playback write reports the error and refreshes durable partial changes', async () => {
  const request = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method === 'PUT')
      return Response.json(
        { error: { code: 'write_failed', message: 'Index failed.' } },
        { status: 409 },
      )
    return Response.json({
      ...savedMediaPage,
      items: [],
      counts: { all: 0, images: 0, videos: 0, audio: 0, files: 0 },
    })
  })
  vi.stubGlobal('fetch', request)
  const client = createQueryClient()
  const query = mediaQuery('studio', { unseen: 1 })
  client.setQueryData(query.queryKey, savedMediaPage)
  const observer = new QueryObserver(client, query)
  const unsubscribe = observer.subscribe(() => {})
  await expect(
    saveMediaPosition(
      client,
      'studio',
      savedPost.id,
      savedVideo,
      { seconds: 100, duration: 100 },
      false,
    ),
  ).rejects.toThrow('Index failed.')
  expect(request).toHaveBeenCalledTimes(2)
  expect(client.getQueryData(query.queryKey)?.items).toEqual([])
  expect(client.getQueryData(query.queryKey)?.counts.all).toBe(0)
  unsubscribe()
  client.clear()
})
