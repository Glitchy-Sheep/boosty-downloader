import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, test, vi } from 'vitest'

import { useFavorite } from '@/hooks/use-favorite'
import { acceptPosition } from '@/lib/playback-cache'
import { authorQuery, authorsQuery, createQueryClient, postQuery, postsQuery } from '@/lib/queries'
import { savedAuthor, savedList, savedPost, savedRow, savedVideo } from '@/test/post-fixtures'

afterEach(() => vi.unstubAllGlobals())

function pendingResponse() {
  let resolve!: (response: Response) => void
  const response = new Promise<Response>(done => { resolve = done })
  return { response, resolve }
}

function setup() {
  const client = createQueryClient()
  client.setQueryData(postQuery('studio', savedPost.id).queryKey, savedPost)
  client.setQueryData(authorQuery('studio').queryKey, savedAuthor)
  client.setQueryData(authorsQuery().queryKey, [savedAuthor])
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  client.setQueryData(postsQuery('studio', { fav: 1 }).queryKey, savedList)
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return { client, wrapper }
}

test('failed favorite restores its own changes while a newer playback position survives', async () => {
  const pending = pendingResponse()
  const request = vi.fn().mockReturnValue(pending.response)
  vi.stubGlobal('fetch', request)
  const { client, wrapper } = setup()
  const hook = renderHook(() => useFavorite('studio', savedPost.id), { wrapper })

  act(() => hook.result.current.toggle())
  await waitFor(() => expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(0))
  expect(hook.result.current.pending).toBe(true)
  act(() => hook.result.current.toggle())
  expect(request).toHaveBeenCalledTimes(1)
  act(() => acceptPosition(client, 'studio', savedPost.id, { ...savedVideo, position_s: 44 }))
  pending.resolve(Response.json({ error: { code: 'write_failed', message: 'Could not save favorite.' } }, { status: 503 }))

  await waitFor(() => expect(hook.result.current.pending).toBe(false))
  expect(hook.result.current.error).toBe('Could not save favorite.')
  expect(client.getQueryData(postQuery('studio', savedPost.id).queryKey)).toMatchObject({
    favorite: true, seen: false, body_html: savedPost.body_html, media: [{ position_s: 44 }],
  })
  expect(client.getQueryData(postsQuery('studio', { fav: 1 }).queryKey)).toEqual(savedList)
  expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(1)
  hook.unmount()
  client.clear()
})

test('completion for one post does not erase another pending favorite or its count', async () => {
  const first = pendingResponse()
  const second = pendingResponse()
  vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => url.includes(savedPost.id) ? first.response : second.response))
  const { client, wrapper } = setup()
  client.setQueryData(postQuery('studio', 'second-post').queryKey, { ...savedPost, id: 'second-post', favorite: false })
  const firstHook = renderHook(() => useFavorite('studio', savedPost.id), { wrapper })
  const secondHook = renderHook(() => useFavorite('studio', 'second-post'), { wrapper })

  act(() => { firstHook.result.current.toggle(); secondHook.result.current.toggle() })
  await waitFor(() => expect(client.getQueryData(postQuery('studio', 'second-post').queryKey)?.favorite).toBe(true))
  first.resolve(Response.json({ post: { ...savedRow, favorite: false }, author: { ...savedAuthor, favorites: 0 } }))
  await waitFor(() => expect(firstHook.result.current.pending).toBe(false))

  expect(secondHook.result.current.pending).toBe(true)
  expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(1)
  second.resolve(Response.json({ post: { ...savedRow, id: 'second-post', favorite: true }, author: savedAuthor }))
  await waitFor(() => expect(secondHook.result.current.pending).toBe(false))
  expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(1)
  firstHook.unmount()
  secondHook.unmount()
  client.clear()
})

test('locked retained posts cannot write favorites', () => {
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  const { client, wrapper } = setup()
  client.setQueryData(postQuery('studio', savedPost.id).queryKey, { ...savedPost, access: 'locked' })
  const hook = renderHook(() => useFavorite('studio', savedPost.id), { wrapper })
  act(() => hook.result.current.toggle())
  expect(request).not.toHaveBeenCalled()
  hook.unmount()
  client.clear()
})

test('a failed favorite remains visible after leaving and returning, and clears on retry', async () => {
  const pending = pendingResponse()
  const request = vi.fn().mockReturnValueOnce(pending.response).mockResolvedValue(Response.json({
    post: { ...savedRow, favorite: false }, author: { ...savedAuthor, favorites: 0 },
  }))
  vi.stubGlobal('fetch', request)
  const { client, wrapper } = setup()
  const first = renderHook(() => useFavorite('studio', savedPost.id), { wrapper })
  act(() => first.result.current.toggle())
  await waitFor(() => expect(request).toHaveBeenCalledOnce())
  first.unmount()
  const returned = renderHook(() => useFavorite('studio', savedPost.id), { wrapper })
  expect(returned.result.current.pending).toBe(true)

  pending.resolve(Response.json({ error: { code: 'write_failed', message: 'Could not save favorite.' } }, { status: 503 }))
  await waitFor(() => expect(returned.result.current.pending).toBe(false))
  expect(returned.result.current.error).toBe('Could not save favorite.')
  expect(client.getQueryData(postQuery('studio', savedPost.id).queryKey)?.favorite).toBe(true)
  act(() => returned.result.current.toggle())
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(returned.result.current.pending).toBe(false))
  expect(returned.result.current.error).toBeNull()
  expect(client.getQueryData(postQuery('studio', savedPost.id).queryKey)?.favorite).toBe(false)
  returned.unmount()
  client.clear()
})

test('a partially saved mark refreshes canonical detail after an index failure', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      return Response.json({ error: { code: 'write_failed', message: 'Index failed.' } }, { status: 409 })
    }
    return Response.json({ ...savedPost, favorite: false })
  }))
  const { client, wrapper } = setup()
  const hook = renderHook(() => ({
    favorite: useFavorite('studio', savedPost.id), post: useQuery(postQuery('studio', savedPost.id)),
  }), { wrapper })
  act(() => hook.result.current.favorite.toggle())
  await waitFor(() => expect(hook.result.current.favorite.error).toBe('Index failed.'))
  expect(hook.result.current.post.data?.favorite).toBe(false)
  hook.unmount()
  client.clear()
})
