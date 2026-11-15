import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, test, vi } from 'vitest'

import { useFavorite } from '@/hooks/use-favorite'
import { togglePostMark } from '@/lib/mark-mutations'
import { acceptPosition } from '@/lib/playback-cache'
import {
  authorQuery,
  authorsQuery,
  createQueryClient,
  mediaQuery,
  postQuery,
  postsQuery,
  usePostList,
} from '@/lib/queries'
import { savedMediaPage, savedMediaPost } from '@/test/media-fixtures'
import { savedAuthor, savedList, savedPost, savedRow, savedVideo } from '@/test/post-fixtures'

afterEach(() => vi.unstubAllGlobals())

function deferredResponse() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function mediaFavorite(favorite: boolean) {
  return { ...savedMediaPage, posts: { [savedRow.id]: { ...savedMediaPost, favorite } } }
}

function setup() {
  const client = createQueryClient()
  client.setQueryData(mediaQuery('studio', {}).queryKey, savedMediaPage)
  client.setQueryData(authorQuery('studio').queryKey, savedAuthor)
  client.setQueryData(authorsQuery().queryKey, [savedAuthor])
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

function confirmedFavorite(favorite: boolean): Response {
  return Response.json({
    post: { ...savedRow, favorite },
    author: { ...savedAuthor, favorites: Number(favorite) },
  })
}

test('media query identity includes canonical filters and excludes fullscreen selection', () => {
  expect(mediaQuery('studio', {}).queryKey).toEqual([
    'media',
    'studio',
    { view: 'all', order: 'newest', unseen: false, fav: false },
  ])
  expect(mediaQuery('studio', { view: 'images', open: 'one' }).queryKey).toEqual(
    mediaQuery('studio', { view: 'images', open: 'two' }).queryKey,
  )
  expect(mediaQuery('studio', { view: 'images', fav: 1 }).queryKey).not.toEqual(
    mediaQuery('studio', { view: 'images', unseen: 1 }).queryKey,
  )
})

test('a direct Media heart updates shared posts and author counts without fetching a post', async () => {
  const write = deferredResponse()
  const fetcher = vi
    .fn<typeof fetch>()
    .mockImplementation(async (_input, init) =>
      init?.method === 'PUT' ? write.promise : Response.json(mediaFavorite(false)),
    )
  vi.stubGlobal('fetch', fetcher)
  const { client, wrapper } = setup()
  const hook = renderHook(
    () => ({
      heart: useFavorite('studio', savedRow.id),
      media: useQuery(mediaQuery('studio', {})),
    }),
    { wrapper },
  )
  act(() => hook.result.current.heart.toggle())
  await waitFor(() =>
    expect(hook.result.current.media.data?.posts[savedRow.id]?.favorite).toBe(false),
  )
  expect(hook.result.current.heart.pending).toBe(true)
  expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(0)
  expect(client.getQueryData(authorsQuery().queryKey)?.[0]?.favorites).toBe(0)
  expect(client.getQueryData(postQuery('studio', savedRow.id).queryKey)).toBeUndefined()
  write.resolve(confirmedFavorite(false))
  await waitFor(() => expect(hook.result.current.heart.pending).toBe(false))
  expect(fetcher.mock.calls.map(([url, init]) => ({ url, method: init?.method ?? 'GET' }))).toEqual(
    [
      { url: `/api/authors/studio/posts/${savedRow.id}/marks`, method: 'PUT' },
      { url: '/api/authors/studio/media', method: 'GET' },
    ],
  )
  hook.unmount()
  client.clear()
})

test('Media access prevents locked hearts and cannot manufacture a seen action from an incomplete summary', () => {
  const request = vi.fn<typeof fetch>()
  vi.stubGlobal('fetch', request)
  const { client } = setup()
  togglePostMark(client, 'studio', savedRow.id, 'seen')
  client.setQueryData(mediaQuery('studio', {}).queryKey, {
    ...savedMediaPage,
    posts: { [savedRow.id]: { ...savedMediaPost, access: 'locked' } },
  })
  togglePostMark(client, 'studio', savedRow.id, 'favorite')
  togglePostMark(client, 'studio', 'unknown', 'favorite')
  expect(request).not.toHaveBeenCalled()
  expect(client.isMutating()).toBe(0)
  client.clear()
})

test.each([
  { timing: 'before', failed: false },
  { timing: 'during', failed: false },
  { timing: 'before', failed: true },
  { timing: 'during', failed: true },
])(
  'a first Media loader $timing a favorite write stays canonical, failed=$failed',
  async ({ timing, failed }) => {
    const write = deferredResponse()
    const initial = deferredResponse()
    let reads = 0
    let writes = 0
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
        if (init?.method === 'PUT') {
          writes++
          return write.promise
        }
        return ++reads === 1 ? initial.promise : Response.json(mediaFavorite(false))
      }),
    )
    const { client } = setup()
    if (timing === 'during') togglePostMark(client, 'studio', savedRow.id, 'favorite')
    const query = mediaQuery('studio', { order: 'oldest', open: 'opaque-video' })
    const loader = client.ensureQueryData(query)
    const fulfilled = expect(loader).resolves.toMatchObject({
      posts: { [savedRow.id]: { favorite: false } },
    })
    await vi.waitFor(() => expect(reads).toBe(1))
    if (timing === 'before') togglePostMark(client, 'studio', savedRow.id, 'favorite')
    await vi.waitFor(() => expect(writes).toBe(1))
    write.resolve(
      failed
        ? Response.json(
            { error: { code: 'write_failed', message: 'Index failed.' } },
            { status: 409 },
          )
        : confirmedFavorite(false),
    )
    await vi.waitFor(() =>
      expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
        phase: 'refreshing',
      }),
    )
    initial.resolve(Response.json(savedMediaPage))
    await fulfilled
    await vi.waitFor(() => expect(client.isMutating()).toBe(0))
    expect(reads).toBe(3)
    expect(client.getQueryData(query.queryKey)?.posts[savedRow.id]?.favorite).toBe(false)
    client.clear()
  },
)

test('pending Media favorites preserve fresh metadata and server-owned Unseen membership on rollback', async () => {
  const write = deferredResponse()
  const freshPost = { ...savedMediaPost, title: 'Fresh title', seen: true }
  vi.stubGlobal(
    'fetch',
    vi
      .fn<typeof fetch>()
      .mockImplementation(async (_url, init) =>
        init?.method === 'PUT'
          ? write.promise
          : Response.json({ ...savedMediaPage, posts: { [savedRow.id]: freshPost } }),
      ),
  )
  const { client } = setup()
  togglePostMark(client, 'studio', savedRow.id, 'favorite')
  const query = mediaQuery('studio', { unseen: 1 })
  const projected = await client.fetchQuery(query)
  expect(projected.posts[savedRow.id]).toEqual({ ...freshPost, favorite: false })
  expect(projected.items).toEqual(savedMediaPage.items)
  expect(projected.counts).toEqual(savedMediaPage.counts)
  write.resolve(
    Response.json({ error: { code: 'write_failed', message: 'Cannot save.' } }, { status: 503 }),
  )
  await vi.waitFor(() => expect(client.isMutating()).toBe(0))
  expect(client.getQueryData(query.queryKey)?.posts[savedRow.id]).toEqual(freshPost)
  expect(client.getQueryState(query.queryKey)?.isInvalidated).toBe(true)
  client.clear()
})

test('a post fetched during a Media favorite provides real row membership for rollback', async () => {
  const write = deferredResponse()
  vi.stubGlobal(
    'fetch',
    vi
      .fn<typeof fetch>()
      .mockImplementation(async (_url, init) =>
        init?.method === 'PUT' ? write.promise : Response.json(savedList),
      ),
  )
  const { client } = setup()
  togglePostMark(client, 'studio', savedRow.id, 'favorite')
  const query = postsQuery('studio', { fav: 1, tag: 'stream' })
  expect((await client.fetchQuery(query)).rows).toEqual([])
  write.resolve(
    Response.json({ error: { code: 'write_failed', message: 'Cannot save.' } }, { status: 503 }),
  )
  await vi.waitFor(() => expect(client.isMutating()).toBe(0))
  expect(client.getQueryData(query.queryKey)?.rows).toEqual(savedList.rows)
  client.clear()
})

test('overlapping post marks and playback change only their fields in shared Media data', async () => {
  const seen = deferredResponse()
  const favorite = deferredResponse()
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi
      .fn<typeof fetch>()
      .mockImplementation(async () => (++writes === 1 ? seen.promise : favorite.promise)),
  )
  const { client } = setup()
  client.setQueryData(postQuery('studio', savedRow.id).queryKey, savedPost)
  togglePostMark(client, 'studio', savedRow.id, 'seen')
  togglePostMark(client, 'studio', savedRow.id, 'favorite')
  await vi.waitFor(() =>
    expect(
      client.getQueryData(mediaQuery('studio', {}).queryKey)?.posts[savedRow.id],
    ).toMatchObject({ seen: true, favorite: false }),
  )
  acceptPosition(
    client,
    'studio',
    savedRow.id,
    { ...savedVideo, position_s: 75 },
    savedVideo.finished,
  )
  seen.resolve(
    Response.json({ post: { ...savedRow, seen: true }, author: { ...savedAuthor, unseen: 1 } }),
  )
  await vi.waitFor(() => expect(writes).toBe(2))
  favorite.resolve(
    Response.json({ error: { code: 'write_failed', message: 'Cannot save.' } }, { status: 503 }),
  )
  await vi.waitFor(() => expect(client.isMutating()).toBe(0))
  const page = client.getQueryData(mediaQuery('studio', {}).queryKey)
  expect(page?.posts[savedRow.id]).toMatchObject({ seen: true, favorite: true })
  expect(page?.items[0]?.position_s).toBe(75)
  client.clear()
})

test('hidden post lists have no active subscription or automatic refetch', async () => {
  const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json(savedList))
  vi.stubGlobal('fetch', request)
  const { client, wrapper } = setup()
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  const hook = renderHook(({ active }) => usePostList('studio', {}, active), {
    wrapper,
    initialProps: { active: false },
  })
  await client.invalidateQueries({ queryKey: ['posts', 'studio'] })
  expect(request).not.toHaveBeenCalled()
  expect(
    client
      .getQueryCache()
      .find({ queryKey: postsQuery('studio', {}).queryKey })
      ?.isActive(),
  ).toBe(false)
  hook.rerender({ active: true })
  await waitFor(() => expect(request).toHaveBeenCalledOnce())
  expect(hook.result.current.data).toEqual(savedList)
  hook.unmount()
  client.clear()
})
