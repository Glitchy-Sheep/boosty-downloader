import { QueryObserver } from '@tanstack/react-query'
import { afterEach, expect, test, vi } from 'vitest'

import type { MediaPage } from '@/lib/api.gen'
import { togglePostMark } from '@/lib/mark-mutations'
import { saveMediaPosition } from '@/lib/playback-mutations'
import { createQueryClient, mediaQuery, postQuery, postsQuery } from '@/lib/queries'
import { savedMediaPage } from '@/test/media-fixtures'
import { savedAuthor, savedList, savedPost, savedRow, savedVideo } from '@/test/post-fixtures'

afterEach(() => vi.unstubAllGlobals())

const emptyMedia: MediaPage = {
  items: [],
  posts: {},
  counts: { all: 0, images: 0, videos: 0, audio: 0, files: 0 },
  missing: 0,
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function deferredJson(body: Promise<unknown>, status = 200): Response {
  const response = Response.json({}, { status })
  response.json = () => body
  return response
}

test.each(['post', 'media'] as const)(
  'a simultaneous %s read and playback response cannot install an older position',
  async (kind) => {
    const read = deferred<unknown>()
    const write = deferred<unknown>()
    const saved = { ...savedVideo, position_s: 80 }
    const canonical =
      kind === 'post' ? { ...savedPost, media: [saved] } : { ...savedMediaPage, items: [saved] }
    let reads = 0
    let writes = 0
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
        if (init?.method === 'PUT') {
          writes++
          return deferredJson(write.promise)
        }
        return ++reads === 1 ? deferredJson(read.promise) : Response.json(canonical)
      }),
    )
    const client = createQueryClient()
    const loader =
      kind === 'post'
        ? client.fetchQuery(postQuery('studio', savedPost.id))
        : client.fetchQuery(mediaQuery('studio', {}))
    const saving = saveMediaPosition(
      client,
      'studio',
      savedPost.id,
      savedVideo,
      { seconds: 80, duration: 100 },
      true,
    )
    await vi.waitFor(() => expect(writes).toBe(1))
    read.resolve(kind === 'post' ? savedPost : savedMediaPage)
    write.resolve(saved)
    await Promise.all([loader, saving])
    const items =
      kind === 'post'
        ? client.getQueryData(postQuery('studio', savedPost.id).queryKey)?.media
        : client.getQueryData(mediaQuery('studio', {}).queryKey)?.items
    expect(items?.[0]?.position_s).toBe(80)
    client.clear()
  },
)

test.each([false, true])(
  'a favorites list loading during a write keeps canonical membership, partial failure=%s',
  async (failed) => {
    const read = deferred<unknown>()
    const write = deferred<unknown>()
    let reads = 0
    let writes = 0
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
        if (init?.method === 'PUT') {
          writes++
          return deferredJson(write.promise, failed ? 503 : 200)
        }
        return ++reads === 1 ? deferredJson(read.promise) : Response.json(emptyMedia)
      }),
    )
    const client = createQueryClient()
    client.setQueryData(mediaQuery('studio', {}).queryKey, savedMediaPage)
    const query = mediaQuery('studio', { fav: 1 })
    const loader = client.fetchQuery(query)
    togglePostMark(client, 'studio', savedRow.id, 'favorite')
    await vi.waitFor(() => expect(writes).toBe(1))
    const result = failed
      ? { error: { code: 'write_failed', message: 'Index update failed.' } }
      : { post: { ...savedRow, favorite: false }, author: { ...savedAuthor, favorites: 0 } }
    write.resolve(result)
    if (failed)
      await vi.waitFor(() =>
        expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
          phase: 'refreshing',
        }),
      )
    else await Promise.resolve()
    read.resolve(savedMediaPage)
    await loader
    await vi.waitFor(() => expect(client.isMutating()).toBe(0))
    expect(client.getQueryData(query.queryKey)).toEqual(emptyMedia)
    client.clear()
  },
)

test('replaying a finished queued track restores Unseen membership after the item left every cache', async () => {
  const saved = { ...savedVideo, position_s: 20, finished: false }
  vi.stubGlobal(
    'fetch',
    vi
      .fn<typeof fetch>()
      .mockImplementation(async (_url, init) =>
        Response.json(init?.method === 'PUT' ? saved : { ...savedMediaPage, items: [saved] }),
      ),
  )
  const client = createQueryClient()
  const query = mediaQuery('studio', { unseen: 1 })
  client.setQueryData(query.queryKey, emptyMedia)
  const observer = new QueryObserver(client, query)
  const unsubscribe = observer.subscribe(() => {})
  await saveMediaPosition(
    client,
    'studio',
    savedPost.id,
    { ...savedVideo, finished: true },
    { seconds: 20, duration: 100 },
    true,
  )
  await vi.waitFor(() => expect(client.getQueryData(query.queryKey)?.items).toEqual([saved]))
  expect(client.getQueryData(query.queryKey)?.counts.all).toBe(1)
  unsubscribe()
  client.clear()
})

test('rollback cannot overwrite the durable mark returned by a first read after a partial write failure', async () => {
  const read = deferred<Response>()
  const write = deferred<Response>()
  let reads = 0
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
      if (init?.method === 'PUT') {
        writes++
        return write.promise
      }
      return ++reads === 1 ? read.promise : Response.json({ ...savedPost, seen: true })
    }),
  )
  const client = createQueryClient()
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  togglePostMark(client, 'studio', savedRow.id, 'seen')
  await vi.waitFor(() => expect(writes).toBe(1))
  const query = postQuery('studio', savedRow.id)
  const loader = client.fetchQuery(query)
  await vi.waitFor(() => expect(reads).toBe(1))
  write.resolve(
    Response.json(
      { error: { code: 'write_failed', message: 'Index update failed.' } },
      { status: 503 },
    ),
  )
  await vi.waitFor(() =>
    expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
      phase: 'refreshing',
    }),
  )
  read.resolve(Response.json(savedPost))
  await expect(loader).resolves.toMatchObject({ seen: true })
  await vi.waitFor(() => expect(client.isMutating()).toBe(0))
  expect(client.getQueryData(query.queryKey)?.seen).toBe(true)
  client.clear()
})

test.each(['failed', 'cancelled'] as const)(
  'a %s first read is not restarted or allowed to reject a successful playback save',
  async (outcome) => {
    const read = deferred<Response>()
    const write = deferred<Response>()
    const saved = { ...savedVideo, position_s: 80 }
    let reads = 0
    let writes = 0
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
        if (init?.method === 'PUT') {
          writes++
          return write.promise
        }
        reads++
        return read.promise
      }),
    )
    const client = createQueryClient()
    const query = mediaQuery('studio', {})
    const loader = client.fetchQuery(query).catch((error: unknown) => error)
    const saving = saveMediaPosition(
      client,
      'studio',
      savedPost.id,
      savedVideo,
      { seconds: 80, duration: 100 },
      true,
    )
    await vi.waitFor(() => expect(writes).toBe(1))
    write.resolve(Response.json(saved))
    await vi.waitFor(() =>
      expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
        phase: 'refreshing',
      }),
    )
    if (outcome === 'failed') read.reject(new Error('Read failed.'))
    else {
      await client.cancelQueries({ queryKey: query.queryKey, exact: true })
      read.resolve(Response.json(savedMediaPage))
    }
    expect(await loader).toBeInstanceOf(Error)
    await expect(saving).resolves.toEqual(saved)
    expect(reads).toBe(1)
    client.clear()
  },
)

test('repeated finished saves from an old player snapshot refresh inventory only once', async () => {
  const saved = { ...savedVideo, position_s: 0, finished: true }
  let reads = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
      if (init?.method === 'PUT') return Response.json(saved)
      reads++
      return Response.json(emptyMedia)
    }),
  )
  const client = createQueryClient()
  const query = mediaQuery('studio', { unseen: 1 })
  client.setQueryData(query.queryKey, savedMediaPage)
  const observer = new QueryObserver(client, query)
  const unsubscribe = observer.subscribe(() => {})
  for (const seconds of [97, 99, 100]) {
    await saveMediaPosition(
      client,
      'studio',
      savedPost.id,
      savedVideo,
      { seconds, duration: 100 },
      true,
    )
    await vi.waitFor(() => expect(client.getQueryData(query.queryKey)?.items).toEqual([]))
  }
  expect(reads).toBe(1)
  unsubscribe()
  client.clear()
})

test('a failed write leaves an unknown finish state that the next successful save reconciles', async () => {
  const saved = { ...savedVideo, position_s: 20, finished: false }
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
      if (init?.method !== 'PUT') return Response.json({ ...savedMediaPage, items: [saved] })
      if (++writes === 1)
        return Response.json(
          { error: { code: 'write_failed', message: 'Index update failed.' } },
          { status: 503 },
        )
      return Response.json(saved)
    }),
  )
  const client = createQueryClient()
  await expect(
    saveMediaPosition(
      client,
      'studio',
      savedPost.id,
      savedVideo,
      { seconds: 100, duration: 100 },
      true,
    ),
  ).rejects.toThrow('Index update failed.')
  const query = mediaQuery('studio', { unseen: 1 })
  client.setQueryData(query.queryKey, emptyMedia)
  const observer = new QueryObserver(client, query)
  const unsubscribe = observer.subscribe(() => {})
  await saveMediaPosition(
    client,
    'studio',
    savedPost.id,
    savedVideo,
    { seconds: 20, duration: 100 },
    true,
  )
  await vi.waitFor(() => expect(client.getQueryData(query.queryKey)?.items).toEqual([saved]))
  expect(client.getQueryData(query.queryKey)?.counts.all).toBe(1)
  unsubscribe()
  client.clear()
})
