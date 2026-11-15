import type { QueryClient } from '@tanstack/react-query'
import { afterEach, expect, test, vi } from 'vitest'

import { togglePostMark } from '@/lib/mark-mutations'
import { createQueryClient, postQuery, postsQuery } from '@/lib/queries'
import { savedAuthor, savedList, savedPost, savedRow } from '@/test/post-fixtures'

afterEach(() => vi.unstubAllGlobals())

function deferredResponse() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

type ReadKind = 'detail' | 'list'

async function loadRows(client: QueryClient, kind: ReadKind) {
  if (kind === 'detail') return [await client.ensureQueryData(postQuery('studio', savedRow.id))]
  return (await client.ensureQueryData(postsQuery('studio', { order: 'oldest' }))).rows
}

function savedFavoriteResponse(favorite: boolean): Response {
  return Response.json({
    post: { ...savedRow, favorite },
    author: { ...savedAuthor, favorites: Number(favorite) },
  })
}

test.each<ReadKind>(['detail', 'list'])(
  'a first %s loader spanning a successful row write resolves canonical data',
  async (kind) => {
    const write = deferredResponse()
    const firstRead = deferredResponse()
    let reads = 0
    let writes = 0
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
        if (options?.method === 'PUT') {
          writes++
          return write.promise
        }
        if (++reads === 1) return firstRead.promise
        if (kind === 'detail') return Response.json({ ...savedPost, favorite: false })
        return Response.json({ ...savedList, rows: [{ ...savedRow, favorite: false }] })
      }),
    )
    const client = createQueryClient()
    client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
    togglePostMark(client, 'studio', savedRow.id, 'favorite')
    await vi.waitFor(() => expect(writes).toBe(1))
    const loader = loadRows(client, kind)
    await vi.waitFor(() => expect(reads).toBe(1))
    write.resolve(savedFavoriteResponse(false))
    await vi.waitFor(() =>
      expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
        phase: 'refreshing',
      }),
    )
    firstRead.resolve(Response.json(kind === 'detail' ? savedPost : savedList))
    await expect(loader).resolves.toMatchObject([{ favorite: false }])
    await vi.waitFor(() => expect(client.isMutating()).toBe(0))
    expect(reads).toBe(3)
    expect(
      client.getQueryData(postQuery('studio', savedRow.id).queryKey)?.favorite ??
        client.getQueryData(postsQuery('studio', { order: 'oldest' }).queryKey)?.rows[0]?.favorite,
    ).toBe(false)
    client.clear()
  },
)

test('an initial loader already running when a row write starts is not cancelled', async () => {
  const write = deferredResponse()
  const firstRead = deferredResponse()
  let reads = 0
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
      if (options?.method === 'PUT') {
        writes++
        return write.promise
      }
      return ++reads === 1 ? firstRead.promise : Response.json({ ...savedPost, favorite: false })
    }),
  )
  const client = createQueryClient()
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  const loader = loadRows(client, 'detail')
  await vi.waitFor(() => expect(reads).toBe(1))
  togglePostMark(client, 'studio', savedRow.id, 'favorite')
  await vi.waitFor(() => expect(writes).toBe(1))
  write.resolve(savedFavoriteResponse(false))
  await vi.waitFor(() =>
    expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
      phase: 'refreshing',
    }),
  )
  firstRead.resolve(Response.json(savedPost))
  await expect(loader).resolves.toMatchObject([{ favorite: false }])
  await vi.waitFor(() => expect(client.isMutating()).toBe(0))
  expect(reads).toBe(3)
  client.clear()
})

test('a first list read retains a confirmed field while the next field is still pending', async () => {
  const favorite = deferredResponse()
  const seen = deferredResponse()
  const firstRead = deferredResponse()
  let reads = 0
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
      if (options?.method === 'PUT') return ++writes === 1 ? favorite.promise : seen.promise
      return ++reads === 1
        ? firstRead.promise
        : Response.json({ ...savedList, rows: [{ ...savedRow, favorite: false }] })
    }),
  )
  const client = createQueryClient()
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  togglePostMark(client, 'studio', savedRow.id, 'favorite')
  togglePostMark(client, 'studio', savedRow.id, 'seen')
  await vi.waitFor(() => expect(writes).toBe(1))
  const loader = loadRows(client, 'list')
  await vi.waitFor(() => expect(reads).toBe(1))
  favorite.resolve(savedFavoriteResponse(false))
  await vi.waitFor(() =>
    expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
      phase: 'refreshing',
    }),
  )
  firstRead.resolve(Response.json(savedList))
  await expect(loader).resolves.toMatchObject([{ favorite: false, seen: true }])
  await vi.waitFor(() => expect(writes).toBe(2))
  seen.resolve(
    Response.json({
      post: { ...savedRow, favorite: false, seen: true },
      author: { ...savedAuthor, favorites: 0, unseen: 1 },
    }),
  )
  await vi.waitFor(() => expect(client.isMutating()).toBe(0))
  client.clear()
})

test('a first read spanning a partial write failure checks the actual saved mark', async () => {
  const write = deferredResponse()
  const firstRead = deferredResponse()
  let reads = 0
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
      if (options?.method === 'PUT') {
        writes++
        return write.promise
      }
      return ++reads === 1 ? firstRead.promise : Response.json({ ...savedPost, seen: true })
    }),
  )
  const client = createQueryClient()
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  togglePostMark(client, 'studio', savedRow.id, 'seen')
  await vi.waitFor(() => expect(writes).toBe(1))
  const loader = loadRows(client, 'detail')
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
  firstRead.resolve(Response.json(savedPost))
  await expect(loader).resolves.toMatchObject([{ seen: true }])
  await vi.waitFor(() => expect(client.isMutating()).toBe(0))
  expect(reads).toBe(3)
  client.clear()
})

test('a cancelled read does not start another fetch after a mark settles', async () => {
  const write = deferredResponse()
  const firstRead = deferredResponse()
  let reads = 0
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockImplementation(async (_input, options) => {
      if (options?.method === 'PUT') {
        writes++
        return write.promise
      }
      reads++
      return firstRead.promise
    }),
  )
  const client = createQueryClient()
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  togglePostMark(client, 'studio', savedRow.id, 'favorite')
  await vi.waitFor(() => expect(writes).toBe(1))
  const loader = loadRows(client, 'detail').catch(() => undefined)
  await vi.waitFor(() => expect(reads).toBe(1))
  await client.cancelQueries({ queryKey: postQuery('studio', savedRow.id).queryKey })
  write.resolve(savedFavoriteResponse(false))
  await vi.waitFor(() =>
    expect(client.getMutationCache().getAll()[0]?.state.context).toMatchObject({
      phase: 'refreshing',
    }),
  )
  firstRead.resolve(Response.json(savedPost))
  await loader
  await Promise.resolve()
  expect(reads).toBe(1)
  client.clear()
})
