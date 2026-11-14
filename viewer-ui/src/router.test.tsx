import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import type { Author, PostDetail, PostList, PostRow } from '@/lib/api.gen'
import { createQueryClient } from '@/lib/queries'
import { createViewerRouter } from '@/router'

beforeEach(() => {
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function renderViewer(address = '/') {
  const queryClient = createQueryClient()
  const router = createViewerRouter(queryClient, createMemoryHistory({ initialEntries: [address] }))
  const view = render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>)
  return { ...view, queryClient, router }
}

test('shows progress while authors load and then the real empty state', async () => {
  let finish: (value: Response) => void = () => { throw new Error('Request has not started') }
  const pending = new Promise<Response>(resolve => { finish = resolve })
  vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending))
  const { queryClient } = renderViewer()

  expect(await screen.findByRole('status')).toHaveTextContent('Loading authors')
  finish(Response.json([]))
  expect(await screen.findByRole('heading', { name: 'Authors' })).toBeVisible()
  expect(screen.getByRole('status')).toHaveTextContent('No authors yet.')
  queryClient.clear()
})

test('retry reloads a failed query and replaces the error with library data', async () => {
  const request = vi.fn()
    .mockResolvedValueOnce(Response.json({ error: { code: 'library_unavailable', message: 'The library is unavailable.' } }, { status: 409 }))
    .mockResolvedValueOnce(Response.json([]))
  vi.stubGlobal('fetch', request)
  const { queryClient } = renderViewer()

  expect(await screen.findByRole('alert')).toHaveTextContent('The library is unavailable.')
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('heading', { name: 'Authors' })).toBeVisible()
  expect(request).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  queryClient.clear()
})

test('unknown local routes have a route back to the library and no authors request', async () => {
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  const { queryClient } = renderViewer('/not-a-library-route')

  expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Back to authors' })).toHaveAttribute('href', '/')
  expect(request).not.toHaveBeenCalled()
  queryClient.clear()
})

const author: Author = {
  name: 'studio', title: 'Studio', description: '', avatar_url: null, cover_url: null,
  posts: 1, unseen: 1, locked: 0, favorites: 0,
  storage: { videos: 0, images: 0, audio: 0, files: 0 },
}
const row: PostRow = {
  id: 'first-post', title: 'A real saved title', created_at: '2026-01-01T00:00:00Z',
  access: 'open', counts: { videos: 0, images: 0, files: 0, audio: 0 }, cover_path: null,
  seen: false, favorite: false, updated: false, missing_media: 0, tier: null, match: null,
}
const detail: PostDetail = {
  ...row, body_html: '', boosty_url: 'https://boosty.to/studio/posts/first-post',
  has_folder: true, media: [], tags: ['001'], post_price_rub: null, tier_price_rub: null,
}
const listing: PostList = { rows: [row], months: [{ month: '2026-01', count: 1 }], total: 1 }

function serveAuthor(posts = listing) {
  const request = vi.fn(async (input: string) => {
    const { pathname } = new URL(input, 'http://localhost')
    if (pathname === '/api/authors/studio') return Response.json(author)
    if (pathname === '/api/authors/studio/tags') return Response.json([{ tag: '001', count: 1 }])
    if (pathname === '/api/authors/studio/posts') return Response.json(posts)
    if (pathname === '/api/authors/studio/posts/first-post') return Response.json(detail)
    return Response.json({ error: { code: 'not_found', message: 'The post was not found.' } }, { status: 404 })
  })
  vi.stubGlobal('fetch', request)
  return request
}

test('author entry opens the first matching post and preserves literal filters', async () => {
  const request = serveAuthor()
  const { queryClient, router } = renderViewer('/a/studio?q=001.0&tag=null&order=oldest')

  expect(await screen.findByRole('heading', { name: row.title, level: 1 })).toBeVisible()
  expect(router.state.location.pathname).toBe('/a/studio/p/first-post')
  expect(router.state.location.search).toMatchObject({ q: '001.0', tag: 'null', order: 'oldest' })
  expect(request.mock.calls.some(([url]) => url.includes('/posts?q=001.0&tag=null&order=oldest'))).toBe(true)
  expect(screen.getAllByRole('main')).toHaveLength(1)
  queryClient.clear()
})

test('an excluded selected post still loads its detail independently', async () => {
  serveAuthor({ rows: [], months: [], total: 0 })
  const { queryClient, router } = renderViewer('/a/studio/p/first-post?q=absent')

  expect(await screen.findByRole('heading', { name: row.title, level: 1 })).toBeVisible()
  expect(router.state.location.pathname).toBe('/a/studio/p/first-post')
  expect(screen.getByRole('region', { name: 'Selected post' })).toHaveTextContent('001')
  queryClient.clear()
})

test('an empty filtered author keeps its controls without inventing a post', async () => {
  serveAuthor({ rows: [], months: [], total: 0 })
  const { queryClient, router } = renderViewer('/a/studio?q=absent')

  expect(await screen.findByRole('region', { name: 'Selected post' })).toHaveTextContent('No posts match these filters.')
  expect(screen.getByRole('textbox', { name: 'Search posts' })).toHaveValue('absent')
  expect(router.state.location.pathname).toBe('/a/studio')
  queryClient.clear()
})

test('a missing post shows the API error while preserving the author sidebar', async () => {
  serveAuthor()
  const { queryClient } = renderViewer('/a/studio/p/missing')

  expect(await screen.findByRole('alert')).toHaveTextContent('The post was not found.')
  expect(screen.getByRole('complementary', { name: 'Posts of Studio' })).toBeVisible()
  expect(screen.getByRole('region', { name: 'Selected post' })).toContainElement(screen.getByRole('alert'))
  queryClient.clear()
})

test('changing authors discards an unsent search draft', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const { pathname } = new URL(input, 'http://localhost')
    if (pathname.endsWith('/tags')) return Response.json([])
    if (pathname.endsWith('/posts')) return Response.json(listing)
    if (pathname.includes('/posts/')) return Response.json(detail)
    const name = pathname.split('/').at(-1)!
    return Response.json({ ...author, name, title: name })
  }))
  const { queryClient, router } = renderViewer('/a/first/p/first-post')
  await screen.findByRole('heading', { name: row.title, level: 1 })

  fireEvent.change(screen.getByRole('textbox', { name: 'Search posts' }), { target: { value: 'draft-from-first' } })
  await act(() => router.navigate({ to: '/a/$author/p/$postId', params: { author: 'second', postId: row.id }, search: {} }))
  await act(() => new Promise(resolve => setTimeout(resolve, 300)))

  expect(router.state.location.pathname).toBe('/a/second/p/first-post')
  expect(router.state.location.search.q).toBeUndefined()
  expect(screen.getByRole('textbox', { name: 'Search posts' })).toHaveValue('')
  queryClient.clear()
})

test('retrying the list on author entry also recovers the index redirect', async () => {
  const request = serveAuthor()
  const success = request.getMockImplementation()!
  let fail = true
  request.mockImplementation(async input => {
    if (input.endsWith('/posts') && fail) {
      return Response.json({ error: { code: 'library_unavailable', message: 'List unavailable.' } }, { status: 503 })
    }
    return success(input)
  })
  const { queryClient, router } = renderViewer('/a/studio')
  const retry = await screen.findByRole('button', { name: 'Retry posts' })
  fail = false
  fireEvent.click(retry)

  expect(await screen.findByRole('heading', { name: row.title, level: 1 })).toBeVisible()
  expect(router.state.location.pathname).toBe('/a/studio/p/first-post')
  expect(screen.queryByText('List unavailable.')).not.toBeInTheDocument()
  queryClient.clear()
})

test('Back discards an unsent draft even when only a kind filter changes', async () => {
  serveAuthor()
  const { queryClient, router } = renderViewer('/a/studio/p/first-post')
  await screen.findByRole('heading', { name: row.title, level: 1 })
  await act(() => router.navigate({ to: '/a/$author/p/$postId', params: { author: 'studio', postId: row.id }, search: { kind: 'images' } }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Search posts' }), { target: { value: 'unsent-before-back' } })
  await act(async () => { router.history.back() })
  await act(() => new Promise(resolve => setTimeout(resolve, 300)))

  expect(router.state.location.search.kind).toBeUndefined()
  expect(router.state.location.search.q).toBeUndefined()
  expect(screen.getByRole('textbox', { name: 'Search posts' })).toHaveValue('')
  queryClient.clear()
})
