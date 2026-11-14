import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { usePostShortcuts } from '@/hooks/use-post-shortcuts'
import { parseFilters, type Filters } from '@/lib/filters'
import { type PostShortcutContext } from '@/lib/post-shortcut-context'
import { authorQuery, createQueryClient, postQuery, postsQuery, tagsQuery } from '@/lib/queries'
import { parseViewerSearch, stringifyViewerSearch } from '@/lib/url-search'
import { createViewerRouter } from '@/router'
import { savedAuthor, savedPost, savedRow } from '@/test/post-fixtures'

beforeEach(() => {
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

const context: PostShortcutContext = {
  author: 'studio',
  postId: savedRow.id,
  filters: { q: 'needle' },
  neighbours: {
    previous: { ...savedRow, id: 'previous' },
    next: { ...savedRow, id: 'next' },
  },
}

test('uses fresh callbacks and context without leaving a listener after unmount', () => {
  const first = vi.fn()
  const next = vi.fn()
  const search = vi.fn()
  const hook = renderHook(
    ({ onPost, value }) =>
      usePostShortcuts({
        readContext: () => value,
        onPost,
        onSearch: search,
      }),
    { initialProps: { onPost: first, value: context } },
  )

  fireEvent.keyDown(document, { code: 'KeyJ', key: 'о' })
  expect(first).toHaveBeenCalledExactlyOnceWith({
    author: 'studio',
    postId: 'next',
    filters: { q: 'needle' },
  })
  hook.rerender({ onPost: next, value: { ...context, filters: { tag: 'updated' } } })
  fireEvent.keyDown(document, { code: 'KeyK', key: 'л' })
  expect(next).toHaveBeenCalledExactlyOnceWith({
    author: 'studio',
    postId: 'previous',
    filters: { tag: 'updated' },
  })
  expect(first).toHaveBeenCalledTimes(1)
  hook.unmount()
  fireEvent.keyDown(document, { code: 'KeyJ' })
  fireEvent.keyDown(document, { code: 'Slash' })
  expect(next).toHaveBeenCalledTimes(1)
  expect(search).not.toHaveBeenCalled()
})

test('search stays available with no list while movement at a boundary does nothing', () => {
  const onPost = vi.fn()
  const onSearch = vi.fn()
  const hook = renderHook(
    ({ neighbours }) =>
      usePostShortcuts({
        readContext: () => ({ ...context, neighbours }),
        onPost,
        onSearch,
      }),
    { initialProps: { neighbours: context.neighbours } },
  )
  hook.rerender({ neighbours: null })
  fireEvent.keyDown(document, { code: 'KeyJ' })
  fireEvent.keyDown(document, { code: 'KeyK' })
  expect(onPost).not.toHaveBeenCalled()
  expect(fireEvent.keyDown(document, { code: 'Slash' })).toBe(false)
  expect(onSearch).toHaveBeenCalledOnce()
  hook.rerender({ neighbours: { previous: null, next: null } })
  fireEvent.keyDown(document, { code: 'KeyJ' })
  expect(onPost).not.toHaveBeenCalled()
  hook.unmount()
})

test('ignores inactive routes, unsupported keys and keyboard owners', () => {
  const readContext = vi.fn<() => PostShortcutContext | null>().mockReturnValue(null)
  const onPost = vi.fn()
  const onSearch = vi.fn()
  const hook = renderHook(() => usePostShortcuts({ readContext, onPost, onSearch }))
  fireEvent.keyDown(document, { code: 'Slash' })
  expect(onSearch).not.toHaveBeenCalled()
  expect(readContext).toHaveBeenCalledOnce()
  fireEvent.keyDown(document, { code: 'KeyF' })
  const input = document.createElement('input')
  document.body.append(input)
  fireEvent.keyDown(input, { code: 'KeyJ' })
  expect(readContext).toHaveBeenCalledOnce()
  expect(onPost).not.toHaveBeenCalled()
  hook.unmount()
})

test.each([
  { key: 'j', order: 'oldest' },
  { key: 'о', order: 'oldest' },
  { key: 'j', order: 'newest' },
  { key: 'о', order: 'newest' },
] as const)(
  'ten synchronous $key presses advance ten posts in $order order',
  async ({ key, order }) => {
    const client = createQueryClient()
    const filters: Filters = {
      q: 'literal + query',
      tag: 'keyboard',
      unseen: 1,
      fav: 1,
      kind: 'images',
      locked: 1,
      incomplete: 1,
      order: order === 'oldest' ? 'oldest' : undefined,
    }
    const posts = Array.from({ length: 12 }, (_, index) => ({
      ...savedRow,
      id: `post-${index}`,
      title: `Reading post ${index}`,
      created_at: new Date(Date.UTC(2026, 0, index + 1)).toISOString(),
    }))
    if (order === 'newest') posts.reverse()
    const first = posts[0]
    const tenth = posts[10]
    if (!first || !tenth) throw new Error('Missing burst fixture rows')
    client.setQueryData(authorQuery('studio').queryKey, savedAuthor)
    client.setQueryData(tagsQuery('studio').queryKey, [])
    client.setQueryData(postsQuery('studio', filters).queryKey, {
      rows: posts,
      total: posts.length,
      months: [],
    })
    for (const post of posts)
      client.setQueryData(postQuery('studio', post.id).queryKey, { ...savedPost, ...post })
    const history = createMemoryHistory({
      initialEntries: [`/a/studio/p/${first.id}${stringifyViewerSearch(filters)}`],
    })
    const router = createViewerRouter(client, history)
    const selections: string[] = []
    const unsubscribe = history.subscribe(({ location, action }) => {
      if (action.type === 'PUSH') selections.push(location.pathname)
    })
    const view = render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
    await screen.findByRole('heading', { name: first.title, level: 1 })

    act(() => {
      for (let index = 0; index < 10; index++)
        fireEvent.keyDown(document, { code: 'KeyJ', key, repeat: index > 0 })
      expect(history.location.pathname).toBe(`/a/studio/p/${tenth.id}`)
      expect(parseFilters(parseViewerSearch(history.location.search))).toEqual(
        parseFilters(filters),
      )
    })
    expect(selections).toEqual(posts.slice(1, 11).map((post) => `/a/studio/p/${post.id}`))
    await screen.findByRole('heading', { name: tenth.title, level: 1 })
    act(() => {
      for (let index = 0; index < 10; index++)
        fireEvent.keyDown(document, { code: 'KeyK', key: 'л' })
      expect(history.location.pathname).toBe(`/a/studio/p/${first.id}`)
    })
    await screen.findByRole('heading', { name: first.title, level: 1 })
    fireEvent.keyDown(document, { code: 'Slash' })
    const search = screen.getByRole<HTMLInputElement>('textbox', { name: 'Search posts' })
    expect(search).toHaveFocus()
    expect(search.selectionStart).toBe(0)
    expect(search.selectionEnd).toBe(filters.q?.length)
    view.unmount()
    unsubscribe()
    client.clear()
  },
)
