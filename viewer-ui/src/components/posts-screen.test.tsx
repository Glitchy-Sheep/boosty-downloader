import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import type { MediaPage, PostDetail, PostList } from '@/lib/api.gen'
import { createQueryClient, postQuery } from '@/lib/queries'
import { createViewerRouter } from '@/router'
import { savedAuthor, savedList, savedPost, savedRow } from '@/test/post-fixtures'

const emptyMedia: MediaPage = {
  items: [],
  posts: {},
  missing: 0,
  counts: { all: 0, images: 0, videos: 0, audio: 0, files: 0 },
}
const secondPost: PostDetail = {
  ...savedPost,
  id: 'second-post',
  title: 'Second saved post',
  created_at: '2026-01-01T00:00:00Z',
}
const listing: PostList = {
  ...savedList,
  rows: [savedRow, secondPost],
  total: 2,
  months: [{ month: '2026-01', count: 2 }],
}
const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')
const originalScrollIntoView = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  'scrollIntoView',
)

beforeEach(() => {
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(360)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(240)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(360)
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(240)
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value(this: HTMLElement, options: ScrollToOptions): void {
      this.scrollTop = Math.max(0, options.top ?? this.scrollTop)
      this.dispatchEvent(new Event('scroll'))
    },
  })
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
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, 'scrollTo', originalScrollTo)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
  if (originalScrollIntoView)
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
})

function serve(posts = listing, detail = savedPost) {
  const request = vi.fn(async (input: string) => {
    const { pathname } = new URL(input, 'http://localhost')
    if (pathname === '/api/authors/studio') return Response.json(savedAuthor)
    if (pathname.endsWith('/tags')) return Response.json([{ tag: 'tag', count: 2 }])
    if (pathname.endsWith('/media')) return Response.json(emptyMedia)
    if (pathname.endsWith('/posts')) return Response.json(posts)
    if (pathname.endsWith('/posts/first-post')) return Response.json(detail)
    if (pathname.endsWith('/posts/second-post')) return Response.json(secondPost)
    throw new Error(`Unexpected request ${input}`)
  })
  vi.stubGlobal('fetch', request)
  return request
}

function setup(address = '/a/studio/p/first-post', prepare?: (client: QueryClient) => void) {
  const client = createQueryClient()
  prepare?.(client)
  const router = createViewerRouter(client, createMemoryHistory({ initialEntries: [address] }))
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { client, router, ...view }
}

function deferredResponse() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

test('post tags toggle within the current filters and clearing body search keeps the selection', async () => {
  serve(listing, { ...savedPost, body_html: '<p>Retained lesson</p>' })
  const { client, router, unmount } = setup('/a/studio/p/first-post?q=Retained&kind=videos')
  await screen.findByRole('heading', { name: savedPost.title })
  const tag = screen.getByRole('button', { name: '#tag' })
  fireEvent.click(tag)
  await waitFor(() =>
    expect(router.state.location.search).toMatchObject({
      q: 'Retained',
      kind: 'videos',
      tag: 'tag',
    }),
  )
  expect(tag).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(tag)
  await waitFor(() => expect(router.state.location.search.tag).toBeUndefined())
  fireEvent.click(screen.getByRole('button', { name: 'Clear search in this post' }))
  await waitFor(() => expect(router.state.location.search.q).toBeUndefined())
  expect(router.state.location.search.kind).toBe('videos')
  expect(router.state.location.pathname).toBe('/a/studio/p/first-post')
  unmount()
  client.clear()
})

test('timeline and pager navigation preserve filters, while authored post links use their own address', async () => {
  serve(listing, {
    ...savedPost,
    body_html: '<a href="/a/studio/p/second-post">Referenced post</a>',
  })
  const { client, router, unmount } = setup('/a/studio/p/first-post?kind=videos&order=oldest')
  const sidebar = await screen.findByRole('complementary', { name: 'Posts of Studio' })
  const next = await within(sidebar).findByRole('link', { name: /Second saved post/ })
  expect(next).toHaveAttribute('href', '/a/studio/p/second-post?kind=videos&order=oldest')
  fireEvent.click(next)
  await screen.findByRole('heading', { name: secondPost.title })
  expect(router.state.location.search).toMatchObject({ kind: 'videos', order: 'oldest' })
  const pager = screen.getByRole('navigation', { name: 'Post navigation' })
  fireEvent.click(within(pager).getByRole('link', { name: /Saved post/ }))
  await screen.findByRole('heading', { name: savedPost.title })
  fireEvent.click(screen.getByRole('link', { name: 'Referenced post' }))
  await screen.findByRole('heading', { name: secondPost.title })
  expect(router.state.location.search.kind).toBeUndefined()
  expect(router.state.location.search.order).toBeUndefined()
  unmount()
  client.clear()
})

test('an empty author can change and clear filters without inventing a selected post', async () => {
  serve({ rows: [], months: [], total: 0 })
  const { client, router, unmount } = setup('/a/studio')
  expect(await screen.findByText('No posts saved for this author.')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Photos' }))
  await waitFor(() => expect(router.state.location.search.kind).toBe('images'))
  expect(screen.getByText('No posts match these filters.')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  await waitFor(() => expect(router.state.location.search.kind).toBeUndefined())
  expect(router.state.location.pathname).toBe('/a/studio')
  expect(screen.getByText('No posts saved for this author.')).toBeVisible()
  unmount()
  client.clear()
})

test('list and tag retry recover independently without replacing the readable selected post', async () => {
  const request = serve()
  const original = request.getMockImplementation()!
  let failLists = true
  let failTags = true
  request.mockImplementation(async (input) => {
    if ((input.endsWith('/posts') && failLists) || (input.endsWith('/tags') && failTags))
      return Response.json(
        { error: { code: 'read_failed', message: 'Index temporarily unavailable.' } },
        { status: 503 },
      )
    return original(input)
  })
  const { client, container, unmount } = setup()
  await screen.findByRole('heading', { name: savedPost.title })
  const body = container.querySelector('.post-body')!
  failTags = false
  fireEvent.click(await screen.findByRole('button', { name: 'Retry tags' }))
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Retry tags' })).not.toBeInTheDocument(),
  )
  expect(screen.getByRole('button', { name: 'Retry posts' })).toBeEnabled()
  failLists = false
  fireEvent.click(screen.getByRole('button', { name: 'Retry posts' }))
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Retry posts' })).not.toBeInTheDocument(),
  )
  expect(container.querySelector('.post-body')).toBe(body)
  expect(screen.getByRole('combobox', { name: 'Tag' })).toHaveTextContent('tag (2)')
  unmount()
  client.clear()
})

test('hidden Posts retains its body and unsent search through query collection, then refreshes on return', async () => {
  const request = serve()
  const original = request.getMockImplementation()!
  const { client, router, container, unmount } = setup(undefined, (queryClient) => {
    queryClient.setQueryDefaults(['post', 'studio'], { gcTime: 20 })
    queryClient.setQueryDefaults(['posts', 'studio'], { gcTime: 20 })
  })
  await screen.findByRole('heading', { name: savedPost.title })
  const pane = container.querySelector('.author-pane[data-tab="posts"]')!
  const body = pane.querySelector('.post-body')!
  const search = screen.getByRole('textbox', { name: 'Search posts' })
  fireEvent.change(search, { target: { value: 'draft held while hidden' } })
  fireEvent.click(screen.getByRole('link', { name: 'Media' }))
  await waitFor(() => expect(pane).toHaveAttribute('inert'))
  await waitFor(() =>
    expect(client.getQueryData(postQuery('studio', savedPost.id).queryKey)).toBeUndefined(),
  )
  await act(() => new Promise((resolve) => setTimeout(resolve, 250)))
  expect(router.state.location.pathname).toBe('/a/studio/media')
  expect(router.state.location.search.q).toBeUndefined()
  expect(pane.querySelector('.post-body')).toBe(body)
  expect(search).toHaveValue('draft held while hidden')
  const count = request.mock.calls.length
  await client.invalidateQueries({ queryKey: ['post', 'studio'] })
  expect(request.mock.calls).toHaveLength(count)
  request.mockImplementation(async (input) =>
    input.endsWith('/posts/first-post')
      ? Response.json({ ...savedPost, title: 'Canonical title after return' })
      : original(input),
  )
  fireEvent.click(screen.getByRole('link', { name: 'Posts' }))
  await screen.findByRole('heading', { name: 'Canonical title after return' })
  await waitFor(() => expect(router.state.location.search.q).toBe('draft held while hidden'))
  expect(container.querySelector('.author-pane[data-tab="posts"]')).toBe(pane)
  unmount()
  client.clear()
})

test.each(['empty', 'error'] as const)(
  'a retained %s post pane remains until delayed Media finishes',
  async (kind) => {
    const request = serve({ rows: [], months: [], total: 0 })
    const original = request.getMockImplementation()!
    const pending = deferredResponse()
    request.mockImplementation(async (input) => {
      if (input.endsWith('/media')) return pending.promise
      if (kind === 'error' && input.endsWith('/posts/first-post'))
        return Response.json(
          { error: { code: 'read_failed', message: 'Saved post unavailable.' } },
          { status: 503 },
        )
      return original(input)
    })
    const { client, container, unmount } = setup(kind === 'empty' ? '/a/studio' : undefined)
    const label = kind === 'empty' ? 'No posts saved for this author.' : 'Saved post unavailable.'
    await screen.findByText(label)
    const pane = container.querySelector('.author-pane[data-tab="posts"]')!
    fireEvent.click(screen.getByRole('link', { name: 'Media' }))
    await waitFor(() => expect(pane).toHaveAttribute('inert'))
    expect(pane).toHaveAttribute('data-shown')
    expect(pane).toHaveTextContent(label)
    pending.resolve(Response.json(emptyMedia))
    await waitFor(() => expect(pane).not.toHaveAttribute('data-shown'))
    expect(pane).toHaveTextContent(label)
    unmount()
    client.clear()
  },
)

test('Posts search shortcut selects its text and hidden Posts ignores navigation and marks', async () => {
  serve()
  const { client, router, container, unmount } = setup('/a/studio/p/first-post?q=saved')
  await screen.findByRole('heading', { name: savedPost.title })
  fireEvent.keyDown(document, { code: 'Slash', key: '/' })
  const input = screen.getByRole('textbox', { name: 'Search posts' }) as HTMLInputElement
  expect(input).toHaveFocus()
  expect(input.selectionStart).toBe(0)
  expect(input.selectionEnd).toBe(5)
  fireEvent.click(screen.getByRole('link', { name: 'Media' }))
  await waitFor(() =>
    expect(container.querySelector('.author-pane[data-tab="posts"]')).toHaveAttribute('inert'),
  )
  for (const code of ['KeyJ', 'KeyS', 'KeyF', 'Slash', 'BracketLeft'])
    fireEvent.keyDown(document, { code })
  expect(router.history.location.pathname).toBe('/a/studio/media')
  expect(client.isMutating()).toBe(0)
  unmount()
  client.clear()
})

test('desktop header and search shortcut share sidebar state without replacing the post', async () => {
  const originalMedia = window.matchMedia
  vi.stubGlobal('matchMedia', (query: string) => {
    const media = originalMedia(query)
    Object.defineProperty(media, 'matches', { value: query === '(min-width: 768px)' })
    return media
  })
  const width = function (this: HTMLElement): number {
    return this.hasAttribute('data-group') ? 1000 : 360
  }
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(width)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(width)
  localStorage.clear()
  serve()
  const { client, container, unmount } = setup()
  await screen.findByRole('heading', { name: savedPost.title })
  const body = container.querySelector('.post-body')
  const toggle = screen.getByRole('button', { name: 'Hide sidebar' })
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  fireEvent.click(toggle)
  await waitFor(() => expect(toggle).toHaveAttribute('aria-expanded', 'false'))
  expect(toggle).toHaveAccessibleName('Show sidebar')
  expect(container.querySelector('#author-post-sidebar')).toHaveAttribute('inert')
  fireEvent.keyDown(document, { code: 'Slash' })
  expect(screen.getByRole('textbox', { name: 'Search posts' })).toHaveFocus()
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(container.querySelector('.post-body')).toBe(body)
  fireEvent.keyDown(document, { code: 'BracketLeft', key: 'х' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(screen.getByRole('link', { name: 'Media' }))
  await waitFor(() => expect(toggle).toBeDisabled())
  expect(container.querySelector('.post-body')).toBe(body)
  unmount()
  client.clear()
  localStorage.clear()
})
