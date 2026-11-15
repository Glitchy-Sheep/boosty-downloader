import { MutationObserver, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, test, vi } from 'vitest'

import { usePostMarkActions, usePostMarks } from '@/hooks/use-post-marks'
import type { PostRow } from '@/lib/api.gen'
import { markMutationKeys } from '@/lib/mark-keys'
import { acceptPosition } from '@/lib/playback-cache'
import type { PostMarkKind } from '@/lib/post-marks'
import { authorQuery, authorsQuery, createQueryClient, postQuery, postsQuery } from '@/lib/queries'
import { savedAuthor, savedList, savedPost, savedRow, savedVideo } from '@/test/post-fixtures'

afterEach(() => vi.unstubAllGlobals())

function deferredResponse() {
  let resolve!: (response: Response) => void
  const response = new Promise<Response>((done) => {
    resolve = done
  })
  return { response, resolve }
}

function setup(row: PostRow = savedRow) {
  const client = createQueryClient()
  client.setQueryData(postQuery('studio', row.id).queryKey, { ...savedPost, ...row })
  client.setQueryData(authorQuery('studio').queryKey, savedAuthor)
  client.setQueryData(authorsQuery().queryKey, [savedAuthor])
  for (const filters of [
    {},
    { fav: 1 as const },
    { unseen: 1 as const },
    { fav: 1 as const, unseen: 1 as const },
  ]) {
    client.setQueryData(postsQuery('studio', filters).queryKey, { ...savedList, rows: [row] })
  }
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

function failedResponse(): Response {
  return Response.json(
    { error: { code: 'write_failed', message: 'Could not save mark.' } },
    { status: 503 },
  )
}

test('acknowledges Updated optimistically even though the historical seen mark is true', async () => {
  const pending = deferredResponse()
  const fetcher = vi.fn<typeof fetch>().mockReturnValue(pending.response)
  vi.stubGlobal('fetch', fetcher)
  const row = { ...savedRow, seen: true, updated: true }
  const { client, wrapper } = setup(row)
  const hook = renderHook(() => usePostMarks('studio', row.id), { wrapper })
  act(() => hook.result.current.seen.toggle())
  await waitFor(() => expect(hook.result.current.seen.pending).toBe(true))
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
  expect(fetcher.mock.calls[0]?.[1]?.body).toBe('{"seen":true}')
  expect(client.getQueryData(postQuery('studio', row.id).queryKey)).toMatchObject({
    seen: true,
    updated: false,
    favorite: true,
  })
  expect(client.getQueryData(postsQuery('studio', { unseen: 1 }).queryKey)).toEqual({
    rows: [],
    total: 0,
    months: [],
  })
  expect(client.getQueryData(authorQuery('studio').queryKey)?.unseen).toBe(1)
  expect(client.getQueryData(authorsQuery().queryKey)?.[0]?.unseen).toBe(1)
  pending.resolve(
    Response.json({ post: { ...row, updated: false }, author: { ...savedAuthor, unseen: 1 } }),
  )
  await waitFor(() => expect(hook.result.current.seen.pending).toBe(false))
  expect(hook.result.current.seen.error).toBeNull()
  hook.unmount()
  client.clear()
})

test('a row heart writes without fetching or creating a post detail', async () => {
  const pending = deferredResponse()
  const fetcher = vi.fn<typeof fetch>().mockReturnValue(pending.response)
  vi.stubGlobal('fetch', fetcher)
  const { client, wrapper } = setup()
  client.removeQueries({ queryKey: postQuery('studio', savedRow.id).queryKey })
  const hook = renderHook(() => usePostMarks('studio', savedRow.id), { wrapper })
  act(() => {
    hook.result.current.favorite.toggle()
    hook.result.current.favorite.toggle()
  })
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
  expect(fetcher.mock.calls[0]?.[1]?.method).toBe('PUT')
  expect(client.getQueryData(postQuery('studio', savedRow.id).queryKey)).toBeUndefined()
  expect(client.getQueryData(postsQuery('studio', {}).queryKey)?.rows[0]?.favorite).toBe(false)
  pending.resolve(
    Response.json({
      post: { ...savedRow, favorite: false },
      author: { ...savedAuthor, favorites: 0 },
    }),
  )
  await waitFor(() => expect(hook.result.current.favorite.pending).toBe(false))
  expect(client.getQueryData(postQuery('studio', savedRow.id).queryKey)).toBeUndefined()
  expect(fetcher).toHaveBeenCalledOnce()
  hook.unmount()
  client.clear()
})

test('an older favorite response cannot erase a pending seen mark or newer playback', async () => {
  const favorite = deferredResponse()
  const seen = deferredResponse()
  const fetcher = vi
    .fn<typeof fetch>()
    .mockReturnValueOnce(favorite.response)
    .mockReturnValueOnce(seen.response)
  vi.stubGlobal('fetch', fetcher)
  const { client, wrapper } = setup()
  const hook = renderHook(() => usePostMarks('studio', savedRow.id), { wrapper })
  act(() => {
    hook.result.current.favorite.toggle()
    hook.result.current.seen.toggle()
  })
  const key = postQuery('studio', savedRow.id).queryKey
  await waitFor(() =>
    expect(client.getQueryData(key)).toMatchObject({ favorite: false, seen: true }),
  )
  expect(fetcher).toHaveBeenCalledOnce()
  act(() =>
    acceptPosition(
      client,
      'studio',
      savedRow.id,
      { ...savedVideo, position_s: 48 },
      savedVideo.finished,
    ),
  )
  favorite.resolve(
    Response.json({
      post: { ...savedRow, favorite: false },
      author: { ...savedAuthor, favorites: 0 },
    }),
  )
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  expect(client.getQueryData(key)).toMatchObject({
    favorite: false,
    seen: true,
    media: [{ position_s: 48 }],
  })
  expect(client.getQueryData(authorQuery('studio').queryKey)).toMatchObject({
    unseen: 1,
    favorites: 0,
  })
  seen.resolve(failedResponse())
  await waitFor(() => expect(hook.result.current.seen.pending).toBe(false))
  expect(client.getQueryData(key)).toMatchObject({
    favorite: false,
    seen: false,
    media: [{ position_s: 48 }],
  })
  expect(client.getQueryData(postsQuery('studio', { fav: 1, unseen: 1 }).queryKey)?.rows).toEqual(
    [],
  )
  expect(client.getQueryData(postsQuery('studio', { unseen: 1 }).queryKey)?.rows[0]?.favorite).toBe(
    false,
  )
  hook.unmount()
  client.clear()
})

test.each<PostMarkKind>(['seen', 'favorite'])(
  'both failures restore shared filtered membership when %s starts first',
  async (firstKind) => {
    const first = deferredResponse()
    const second = deferredResponse()
    const fetcher = vi
      .fn<typeof fetch>()
      .mockReturnValueOnce(first.response)
      .mockReturnValueOnce(second.response)
    vi.stubGlobal('fetch', fetcher)
    const { client, wrapper } = setup()
    const hook = renderHook(() => usePostMarks('studio', savedRow.id), { wrapper })
    const secondKind = firstKind === 'seen' ? 'favorite' : 'seen'
    act(() => hook.result.current[firstKind].toggle())
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
    act(() => hook.result.current[secondKind].toggle())
    const detail = postQuery('studio', savedRow.id).queryKey
    await waitFor(() =>
      expect(client.getQueryData(detail)).toMatchObject({ seen: true, favorite: false }),
    )
    first.resolve(failedResponse())
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
    expect(client.getQueryData(postsQuery('studio', { fav: 1, unseen: 1 }).queryKey)?.total).toBe(0)
    second.resolve(failedResponse())
    await waitFor(() => expect(hook.result.current[secondKind].pending).toBe(false))
    expect(client.getQueryData(detail)).toMatchObject({ seen: false, favorite: true })
    expect(client.getQueryData(postsQuery('studio', { fav: 1, unseen: 1 }).queryKey)).toEqual(
      savedList,
    )
    expect(client.getQueryData(authorQuery('studio').queryKey)).toEqual(savedAuthor)
    expect(client.getQueryData(authorsQuery().queryKey)).toEqual([savedAuthor])
    hook.unmount()
    client.clear()
  },
)

test('fresh detail, filters and author reads retain pending marks and accept new metadata', async () => {
  const favorite = deferredResponse()
  const seen = deferredResponse()
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      if (options?.method === 'PUT') return ++writes === 1 ? favorite.response : seen.response
      if (typeof input !== 'string') throw new Error('Expected a relative API URL')
      const url = input
      if (url.includes('/posts/')) return Response.json({ ...savedPost, title: 'Fresh title' })
      if (url.includes('/posts')) return Response.json(savedList)
      if (url === '/api/authors') return Response.json([{ ...savedAuthor, title: 'Fresh author' }])
      return Response.json({ ...savedAuthor, title: 'Fresh author' })
    }),
  )
  const { client, wrapper } = setup()
  const hook = renderHook(() => usePostMarks('studio', savedRow.id), { wrapper })
  act(() => {
    hook.result.current.favorite.toggle()
    hook.result.current.seen.toggle()
  })
  const detail = postQuery('studio', savedRow.id)
  await waitFor(() => expect(client.getQueryData(detail.queryKey)?.seen).toBe(true))
  await act(async () => {
    await client.fetchQuery({ ...detail, staleTime: 0 })
    await client.fetchQuery(postsQuery('studio', { q: 'saved', fav: 1 }))
    await client.fetchQuery({ ...authorQuery('studio'), staleTime: 0 })
    await client.fetchQuery({ ...authorsQuery(), staleTime: 0 })
  })
  expect(client.getQueryData(detail.queryKey)).toMatchObject({
    favorite: false,
    seen: true,
    title: 'Fresh title',
  })
  expect(client.getQueryData(postsQuery('studio', { q: 'saved', fav: 1 }).queryKey)?.total).toBe(0)
  expect(client.getQueryData(authorQuery('studio').queryKey)).toMatchObject({
    favorites: 0,
    unseen: 1,
    title: 'Fresh author',
  })
  expect(client.getQueryData(authorsQuery().queryKey)?.[0]).toMatchObject({
    favorites: 0,
    unseen: 1,
    title: 'Fresh author',
  })
  favorite.resolve(
    Response.json({
      post: { ...savedRow, favorite: false },
      author: { ...savedAuthor, favorites: 0 },
    }),
  )
  await waitFor(() => expect(writes).toBe(2))
  seen.resolve(
    Response.json({
      post: { ...savedRow, favorite: false, seen: true },
      author: { ...savedAuthor, favorites: 0, unseen: 1 },
    }),
  )
  await waitFor(() => expect(hook.result.current.seen.pending).toBe(false))
  expect(client.getQueryData(detail.queryKey)?.title).toBe('Fresh title')
  hook.unmount()
  client.clear()
})

test('an index failure after saving seen refreshes canonical data rather than keeping rollback', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
      if (options?.method === 'PUT') return failedResponse()
      return Response.json({ ...savedPost, seen: true, updated: false })
    }),
  )
  const { client, wrapper } = setup()
  const hook = renderHook(
    () => ({
      marks: usePostMarks('studio', savedRow.id),
      post: useQuery(postQuery('studio', savedRow.id)),
    }),
    { wrapper },
  )
  act(() => hook.result.current.marks.seen.toggle())
  await waitFor(() => expect(hook.result.current.marks.seen.error).toBe('Could not save mark.'))
  expect(hook.result.current.post.data).toMatchObject({ seen: true, updated: false })
  hook.unmount()
  client.clear()
})

test('failed favorite restores a filtered query opened during the pending write', async () => {
  const pending = deferredResponse()
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
      if (options?.method === 'PUT') return pending.response
      return Response.json(savedList)
    }),
  )
  const { client, wrapper } = setup()
  const hook = renderHook(() => usePostMarks('studio', savedRow.id), { wrapper })
  act(() => hook.result.current.favorite.toggle())
  await waitFor(() => expect(hook.result.current.favorite.pending).toBe(true))
  const lateQuery = postsQuery('studio', { q: 'saved', fav: 1, order: 'oldest' })
  await act(async () => {
    await client.fetchQuery(lateQuery)
  })
  expect(client.getQueryData(lateQuery.queryKey)).toEqual({ rows: [], total: 0, months: [] })
  pending.resolve(failedResponse())
  await waitFor(() => expect(hook.result.current.favorite.pending).toBe(false))
  expect(client.getQueryData(lateQuery.queryKey)).toEqual(savedList)
  hook.unmount()
  client.clear()
})

test('dynamic actions use the supplied current post identity and ignore unknown or locked rows', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () =>
    Response.json({
      post: { ...savedRow, id: 'second', seen: true },
      author: { ...savedAuthor, unseen: 1 },
    }),
  )
  vi.stubGlobal('fetch', fetcher)
  const { client, wrapper } = setup()
  client.setQueryData(postsQuery('studio', {}).queryKey, {
    rows: [
      savedRow,
      { ...savedRow, id: 'second' },
      { ...savedRow, id: 'locked', access: 'locked' },
    ],
    months: [{ month: '2026-01', count: 3 }],
    total: 3,
  })
  const hook = renderHook(() => usePostMarkActions('studio'), { wrapper })
  act(() => {
    hook.result.current.toggleSeen('missing')
    hook.result.current.toggleFavorite('locked')
    hook.result.current.toggleSeen('second')
  })
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
  expect(fetcher.mock.calls[0]?.[0]).toBe('/api/authors/studio/posts/second/marks')
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(client.getQueryData(postQuery('studio', savedRow.id).queryKey)?.seen).toBe(false)
  hook.unmount()
  client.clear()
})

test('a bulk mutation blocks both individual controls without losing their pending state', async () => {
  let finish!: () => void
  const work = new Promise<void>((resolve) => {
    finish = resolve
  })
  const fetcher = vi.fn<typeof fetch>()
  vi.stubGlobal('fetch', fetcher)
  const { client, wrapper } = setup()
  const bulk = new MutationObserver(client, {
    mutationKey: markMutationKeys.bulk('studio'),
    mutationFn: () => work,
  })
  const unsubscribe = bulk.subscribe(() => {})
  const bulkResult = bulk.mutate()
  const hook = renderHook(() => usePostMarks('studio', savedRow.id), { wrapper })
  expect(hook.result.current.seen.pending).toBe(true)
  expect(hook.result.current.favorite.pending).toBe(true)
  act(() => {
    hook.result.current.seen.toggle()
    hook.result.current.favorite.toggle()
  })
  expect(fetcher).not.toHaveBeenCalled()
  await act(async () => {
    finish()
    await bulkResult
  })
  await waitFor(() => expect(hook.result.current.seen.pending).toBe(false))
  unsubscribe()
  hook.unmount()
  client.clear()
})

test.each<PostMarkKind>(['seen', 'favorite'])(
  'row-only rollback preserves a successful %s mark after both actions removed the row',
  async (firstKind) => {
    const first = deferredResponse()
    const second = deferredResponse()
    const fetcher = vi
      .fn<typeof fetch>()
      .mockReturnValueOnce(first.response)
      .mockReturnValueOnce(second.response)
    vi.stubGlobal('fetch', fetcher)
    const { client, wrapper } = setup()
    client.removeQueries({ queryKey: ['post'] })
    client.removeQueries({ queryKey: ['posts'] })
    const key = postsQuery('studio', { fav: 1, unseen: 1 }).queryKey
    client.setQueryData(key, savedList)
    const hook = renderHook(() => usePostMarks('studio', savedRow.id), { wrapper })
    const secondKind = firstKind === 'seen' ? 'favorite' : 'seen'
    act(() => hook.result.current[firstKind].toggle())
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
    expect(client.getQueryData(key)?.rows).toEqual([])
    act(() => hook.result.current[secondKind].toggle())
    await waitFor(() => expect(hook.result.current[secondKind].pending).toBe(true))
    const confirmed = {
      ...savedRow,
      seen: firstKind === 'seen',
      favorite: firstKind !== 'favorite',
    }
    first.resolve(Response.json({ post: confirmed, author: savedAuthor }))
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
    second.resolve(failedResponse())
    await waitFor(() => expect(hook.result.current[secondKind].pending).toBe(false))
    expect(client.getQueryData(key)?.rows).toEqual([])
    expect(client.getQueryData(postQuery('studio', savedRow.id).queryKey)).toBeUndefined()
    expect(client.getQueryData(authorQuery('studio').queryKey)).toMatchObject({
      unseen: firstKind === 'seen' ? 1 : 2,
      favorites: firstKind === 'favorite' ? 0 : 1,
    })
    hook.unmount()
    client.clear()
  },
)

test('row-only rollback retains metadata and unrelated Updated from a newly opened query', async () => {
  const pending = deferredResponse()
  const match = { title: [{ text: 'Fresh', matched: true }], text: null }
  const row = { ...savedRow, seen: true }
  const fresh = {
    ...row,
    updated: true,
    title: 'Fresh title',
    counts: { ...savedRow.counts, images: 2 },
    match,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
      if (options?.method === 'PUT') return pending.response
      return Response.json({ ...savedList, rows: [fresh] })
    }),
  )
  const { client, wrapper } = setup(row)
  client.removeQueries({ queryKey: ['post'] })
  client.removeQueries({ queryKey: ['posts'] })
  client.setQueryData(postsQuery('studio', { fav: 1 }).queryKey, { ...savedList, rows: [row] })
  const hook = renderHook(() => usePostMarks('studio', savedRow.id), { wrapper })
  act(() => hook.result.current.favorite.toggle())
  await waitFor(() => expect(hook.result.current.favorite.pending).toBe(true))
  const query = postsQuery('studio', { q: 'fresh', fav: 1 })
  await act(async () => {
    await client.fetchQuery(query)
  })
  expect(client.getQueryData(query.queryKey)?.rows).toEqual([])
  pending.resolve(failedResponse())
  await waitFor(() => expect(hook.result.current.favorite.pending).toBe(false))
  expect(client.getQueryData(query.queryKey)?.rows).toEqual([fresh])
  hook.unmount()
  client.clear()
})

test('a newly loaded Favorites list includes a pending favorite with known unrestricted membership', async () => {
  const pending = deferredResponse()
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
      if (options?.method === 'PUT') return pending.response
      return Response.json({ rows: [], total: 0, months: [] })
    }),
  )
  const row = { ...savedRow, favorite: false }
  const { client, wrapper } = setup(row)
  const hook = renderHook(() => usePostMarks('studio', row.id), { wrapper })
  act(() => hook.result.current.favorite.toggle())
  await waitFor(() => expect(hook.result.current.favorite.pending).toBe(true))
  const query = postsQuery('studio', { fav: 1, order: 'oldest' })
  await act(async () => {
    await client.fetchQuery(query)
  })
  expect(client.getQueryData(query.queryKey)).toEqual(savedList)
  pending.resolve(failedResponse())
  await waitFor(() => expect(hook.result.current.favorite.pending).toBe(false))
  expect(client.getQueryData(query.queryKey)).toEqual({ rows: [], total: 0, months: [] })
  hook.unmount()
  client.clear()
})
