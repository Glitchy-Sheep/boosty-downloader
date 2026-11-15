import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, test, vi } from 'vitest'

import { useBulkMarks, type BulkMarkSelection } from '@/hooks/use-bulk-marks'
import { usePostMarks } from '@/hooks/use-post-marks'
import { toPostFilters } from '@/lib/filters'
import { markMutationKeys } from '@/lib/mark-keys'
import { authorQuery, authorsQuery, createQueryClient, postQuery, postsQuery } from '@/lib/queries'
import { savedAuthor, savedList, savedPost } from '@/test/post-fixtures'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

function pendingResponse() {
  let resolve!: (response: Response) => void
  const response = new Promise<Response>((done) => {
    resolve = done
  })
  return { response, resolve }
}

function setup() {
  const client = createQueryClient()
  client.setQueryData(authorQuery('studio').queryKey, savedAuthor)
  client.setQueryData(authorsQuery().queryKey, [savedAuthor])
  client.setQueryData(postQuery('studio', savedPost.id).queryKey, savedPost)
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const selection: BulkMarkSelection = {
    author: 'studio',
    filters: toPostFilters({ tag: 'stream', unseen: 1 }),
    seen: true,
    changeCount: 2,
  }
  return { client, wrapper, selection }
}

test('keeps the captured selection and waits for POST when progress becomes inactive', async () => {
  const pending = pendingResponse()
  const request = vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return pending.response
    return Response.json({ active: false, total: null, completed: 0, changed: 0 })
  })
  vi.stubGlobal('fetch', request)
  const { client, wrapper, selection } = setup()
  const hook = renderHook(() => useBulkMarks('studio'), { wrapper })
  act(() => {
    expect(hook.result.current.start(selection)).toBe(true)
  })
  selection.filters.tag = 'changed-after-confirmation'
  await waitFor(() => expect(hook.result.current.progress?.active).toBe(false))
  expect(hook.result.current.pending).toBe(true)
  expect(hook.result.current.operation?.selection.filters.tag).toBe('stream')
  expect(
    request.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === 'POST',
    )?.[1],
  ).toMatchObject({
    body: JSON.stringify({ filters: toPostFilters({ tag: 'stream', unseen: 1 }), seen: true }),
  })
  act(() => {
    expect(hook.result.current.start(selection)).toBe(false)
  })
  pending.resolve(Response.json({ count: 1 }))
  await waitFor(() => expect(hook.result.current.operation?.status).toBe('success'))
  expect(hook.result.current.operation?.count).toBe(1)
  expect(hook.result.current.pending).toBe(false)
  hook.unmount()
  client.clear()
})

test('shares pending progress after leaving and returns the final error without losing earlier marks', async () => {
  const pending = pendingResponse()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return pending.response
      return Response.json({ active: true, total: 3, completed: 2, changed: 1 })
    }),
  )
  const { client, wrapper, selection } = setup()
  const first = renderHook(() => useBulkMarks('studio'), { wrapper })
  act(() => {
    first.result.current.start(selection)
  })
  await waitFor(() => expect(first.result.current.progress?.completed).toBe(2))
  first.unmount()
  const returned = renderHook(() => useBulkMarks('studio'), { wrapper })
  expect(returned.result.current.pending).toBe(true)
  pending.resolve(
    Response.json(
      { error: { code: 'write_failed', message: 'Index update failed.' } },
      { status: 409 },
    ),
  )
  await waitFor(() => expect(returned.result.current.operation?.status).toBe('error'))
  expect(returned.result.current.operation?.error).toBe('Index update failed.')
  expect(returned.result.current.operation?.count).toBeNull()
  expect(client.getQueryState(postQuery('studio', savedPost.id).queryKey)?.isInvalidated).toBe(true)
  expect(client.getQueryState(authorQuery('studio').queryKey)?.isInvalidated).toBe(true)
  expect(client.getQueryState(authorsQuery().queryKey)?.isInvalidated).toBe(true)
  returned.unmount()
  const again = renderHook(() => useBulkMarks('studio'), { wrapper })
  expect(again.result.current.operation?.error).toBe('Index update failed.')
  again.unmount()
  client.clear()
})

test('a bulk finishes and refreshes cached records while no marks component is mounted', async () => {
  const pending = pendingResponse()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return pending.response
      return Response.json({ active: true, total: 3, completed: 1, changed: 1 })
    }),
  )
  const { client, wrapper, selection } = setup()
  const hook = renderHook(() => useBulkMarks('studio'), { wrapper })
  act(() => {
    hook.result.current.start(selection)
  })
  await waitFor(() => expect(hook.result.current.progress?.completed).toBe(1))
  hook.unmount()
  pending.resolve(Response.json({ count: 2 }))
  await waitFor(() =>
    expect(client.isMutating({ mutationKey: markMutationKeys.bulk('studio') })).toBe(0),
  )
  expect(client.getQueryState(postQuery('studio', savedPost.id).queryKey)?.isInvalidated).toBe(true)
  const returned = renderHook(() => useBulkMarks('studio'), { wrapper })
  expect(returned.result.current.operation).toMatchObject({ status: 'success', count: 2 })
  returned.unmount()
  client.clear()
})

test('blocks other-author submissions and pending single marks before issuing a bulk request', async () => {
  const pending = pendingResponse()
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  const { client, wrapper, selection } = setup()
  const single = client.getMutationCache().build(client, {
    mutationKey: markMutationKeys.single('studio', savedPost.id, 'seen'),
    mutationFn: () => pending.response,
  })
  const writing = single.execute(undefined)
  const hook = renderHook(() => useBulkMarks('studio'), { wrapper })
  expect(hook.result.current.blocked).toBe(true)
  act(() => {
    expect(hook.result.current.start(selection)).toBe(false)
    expect(hook.result.current.start({ ...selection, author: 'another' })).toBe(false)
  })
  expect(request).not.toHaveBeenCalled()
  pending.resolve(Response.json({}))
  await act(() => writing.then(() => {}))
  await waitFor(() => expect(hook.result.current.blocked).toBe(false))
  hook.unmount()
  client.clear()
})

test('progress failures do not cancel or complete a bulk and stop polling when POST settles', async () => {
  const pending = pendingResponse()
  const request = vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return pending.response
    return Response.json(
      { error: { code: 'read_failed', message: 'Progress is unavailable.' } },
      { status: 503 },
    )
  })
  vi.stubGlobal('fetch', request)
  const { client, wrapper, selection } = setup()
  const hook = renderHook(() => useBulkMarks('studio'), { wrapper })
  act(() => {
    hook.result.current.start(selection)
  })
  await waitFor(() =>
    expect(hook.result.current.progressError?.message).toBe('Progress is unavailable.'),
  )
  expect(hook.result.current.pending).toBe(true)
  pending.resolve(Response.json({ count: 2 }))
  await waitFor(() => expect(hook.result.current.operation?.status).toBe('success'))
  vi.useFakeTimers()
  const count = request.mock.calls.length
  await act(() => vi.advanceTimersByTimeAsync(1000))
  expect(request).toHaveBeenCalledTimes(count)
  hook.unmount()
  client.clear()
})

test('refreshes durable partial writes on failure and permits an explicit no-op repair retry', async () => {
  let writes = 0
  const request = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      writes += 1
      if (writes === 1)
        return Response.json(
          { error: { code: 'write_failed', message: 'Index failed.' } },
          { status: 409 },
        )
      return Response.json({ count: 0 })
    }
    if (url.endsWith('/progress'))
      return Response.json({ active: false, total: null, completed: 0, changed: 0 })
    return Response.json({ ...savedPost, seen: true })
  })
  vi.stubGlobal('fetch', request)
  const { client, wrapper, selection } = setup()
  const hook = renderHook(
    () => ({
      marks: useBulkMarks('studio'),
      post: useQuery(postQuery('studio', savedPost.id)),
    }),
    { wrapper },
  )
  act(() => {
    hook.result.current.marks.start(selection)
  })
  await waitFor(() => expect(hook.result.current.marks.operation?.status).toBe('error'))
  expect(hook.result.current.post.data?.seen).toBe(true)
  act(() => {
    expect(hook.result.current.marks.start({ ...selection, changeCount: 0 })).toBe(true)
  })
  await waitFor(() => expect(hook.result.current.marks.operation?.status).toBe('success'))
  expect(hook.result.current.marks.operation?.count).toBe(0)
  expect(hook.result.current.marks.operation?.error).toBeNull()
  hook.unmount()
  client.clear()
})

test("bulk refresh preserves another author's pending favorite and refreshes both final counts", async () => {
  const bulkResponse = pendingResponse()
  const favoriteResponse = pendingResponse()
  const otherAuthor = { ...savedAuthor, name: 'other', favorites: 0 }
  let favoriteSaved = false
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return bulkResponse.response
      if (init?.method === 'PUT') return favoriteResponse.response
      return Response.json([
        { ...savedAuthor, unseen: 0 },
        { ...otherAuthor, favorites: Number(favoriteSaved), description: 'Fresh author details' },
      ])
    }),
  )
  const { client, wrapper, selection } = setup()
  client.setQueryData(authorsQuery().queryKey, [savedAuthor, otherAuthor])
  client.setQueryData(authorQuery('other').queryKey, otherAuthor)
  client.setQueryData(postQuery('other', savedPost.id).queryKey, { ...savedPost, favorite: false })
  const hook = renderHook(
    () => ({
      bulk: useBulkMarks('studio'),
      favorite: usePostMarks('other', savedPost.id).favorite,
      authors: useQuery(authorsQuery()),
    }),
    { wrapper },
  )
  act(() => {
    hook.result.current.bulk.start(selection)
    hook.result.current.favorite.toggle()
  })
  await waitFor(() =>
    expect(
      hook.result.current.authors.data?.find((author) => author.name === 'other')?.favorites,
    ).toBe(1),
  )
  bulkResponse.resolve(Response.json({ count: 2 }))
  await waitFor(() => expect(hook.result.current.bulk.pending).toBe(false))
  expect(hook.result.current.favorite.pending).toBe(true)
  expect(hook.result.current.authors.data?.find((author) => author.name === 'studio')?.unseen).toBe(
    0,
  )
  expect(hook.result.current.authors.data?.find((author) => author.name === 'other')).toMatchObject(
    { favorites: 1, description: 'Fresh author details' },
  )
  favoriteSaved = true
  favoriteResponse.resolve(
    Response.json({
      post: { ...savedPost, favorite: true },
      author: { ...otherAuthor, favorites: 1 },
    }),
  )
  await waitFor(() => expect(hook.result.current.favorite.pending).toBe(false))
  expect(
    hook.result.current.authors.data?.find((author) => author.name === 'other')?.favorites,
  ).toBe(1)
  hook.unmount()
  client.clear()
})

test.each([
  { readTiming: 'before', failed: false },
  { readTiming: 'during', failed: false },
  { readTiming: 'before', failed: true },
  { readTiming: 'during', failed: true },
])(
  'preserves a loader started $readTiming bulk marking, failed=$failed',
  async ({ readTiming, failed }) => {
    const write = pendingResponse()
    const staleRead = pendingResponse()
    let reads = 0
    const request = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return write.response
      if (url.endsWith('/progress'))
        return Response.json({ active: true, total: 2, completed: 1, changed: 1 })
      reads += 1
      return reads === 1 ? staleRead.response : Response.json({ ...savedPost, seen: true })
    })
    vi.stubGlobal('fetch', request)
    const { client, wrapper, selection } = setup()
    const query = postQuery('studio', savedPost.id)
    client.removeQueries({ queryKey: query.queryKey })
    const hook = renderHook(() => useBulkMarks('studio'), { wrapper })
    const start = () => {
      act(() => {
        expect(hook.result.current.start(selection)).toBe(true)
      })
    }
    if (readTiming === 'during') start()
    const loader = client.ensureQueryData(query)
    const fulfilled = expect(loader).resolves.toMatchObject({ seen: true })
    await waitFor(() => expect(reads).toBe(1))
    if (readTiming === 'before') start()
    await waitFor(() => expect(hook.result.current.pending).toBe(true))
    const result = failed
      ? Response.json(
          { error: { code: 'write_failed', message: 'Index failed.' } },
          { status: 409 },
        )
      : Response.json({ count: 2 })
    write.resolve(result)
    await waitFor(() => expect(hook.result.current.pending).toBe(false))
    staleRead.resolve(Response.json({ ...savedPost, seen: false }))
    await fulfilled
    expect(reads).toBe(2)
    expect(client.getQueryData(query.queryKey)?.seen).toBe(true)
    expect(hook.result.current.operation?.status).toBe(failed ? 'error' : 'success')
    hook.unmount()
    client.clear()
  },
)
