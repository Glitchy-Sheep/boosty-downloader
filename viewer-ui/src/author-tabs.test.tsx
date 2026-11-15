import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import type { MediaGrid } from '@/components/media-grid'
import type { MediaPage } from '@/lib/api.gen'
import { createQueryClient, mediaQuery, postsQuery } from '@/lib/queries'
import { createViewerRouter } from '@/router'
import { savedMediaPost } from '@/test/media-fixtures'
import { savedAuthor, savedList, savedPost, savedRow, savedVideo } from '@/test/post-fixtures'

// Route tests use stable tile buttons independently of virtual grid measurements.
vi.mock('@/components/media-grid', () => ({
  MediaGrid: ({ page, onOpen, renderFavorite }: ComponentProps<typeof MediaGrid>) => (
    <div>
      {page.items.map((item) => (
        <div key={item.id}>
          <button type="button" onClick={() => onOpen(item.id)}>
            Open {item.id}
          </button>
          {renderFavorite(item.post_id)}
        </div>
      ))}
    </div>
  ),
}))
const photos: MediaPage = {
  items: ['one', 'two', 'three'].map((id) => ({
    ...savedVideo,
    id,
    kind: 'images',
    file_type: 'image',
    path: `${id}.jpg`,
    title: id,
  })),
  posts: { [savedPost.id]: savedMediaPost },
  counts: { all: 3, images: 3, videos: 0, audio: 0, files: 0 },
  missing: 0,
}

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
})
const emptyMedia: MediaPage = {
  items: [],
  posts: {},
  counts: { all: 0, images: 0, videos: 0, audio: 0, files: 0 },
  missing: 0,
}

function serve(media = emptyMedia) {
  const request = vi.fn(async (input: string) => {
    const { pathname } = new URL(input, 'http://localhost')
    if (pathname === '/api/authors/studio') return Response.json(savedAuthor)
    if (pathname.endsWith('/tags')) return Response.json([])
    if (pathname.endsWith('/posts')) return Response.json(savedList)
    if (pathname.endsWith('/media')) return Response.json(media)
    if (pathname.endsWith('/posts/first-post')) return Response.json(savedPost)
    throw new Error(`Unexpected ${input}`)
  })
  vi.stubGlobal('fetch', request)
  return request
}

function setup(address: string | string[] = '/a/studio/media') {
  const client = createQueryClient()
  const router = createViewerRouter(
    client,
    createMemoryHistory({ initialEntries: Array.isArray(address) ? address : [address] }),
  )
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

test('Back to Media closes the retained Posts bulk portal without focusing its hidden trigger', async () => {
  serve()
  const { client, router, unmount } = setup()
  await screen.findByRole('region', { name: 'Author media' })
  await act(() =>
    router.navigate({
      to: '/a/$author/p/$postId',
      params: { author: 'studio', postId: 'first-post' },
      search: {},
    }),
  )
  await screen.findByRole('heading', { name: savedPost.title })
  fireEvent.keyDown(screen.getByRole('button', { name: 'Mark posts' }), { key: 'Enter' })
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Mark all as seen' }))
  expect(await screen.findByRole('dialog')).toHaveTextContent('Mark 1 post as seen?')
  await act(async () => {
    router.history.back()
  })
  await waitFor(() =>
    expect(document.querySelector('.author-pane[data-tab="media"]')).toHaveAttribute('data-shown'),
  )
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(
    document.querySelector('.author-pane[data-tab="posts"]')?.contains(document.activeElement),
  ).toBe(false)
  unmount()
  client.clear()
})

test('a stale Media return keeps Posts inert and visible until its new list resolves', async () => {
  const request = serve()
  const original = request.getMockImplementation()!
  const { client, router, unmount } = setup()
  await screen.findByRole('region', { name: 'Author media' })
  await act(() =>
    router.navigate({
      to: '/a/$author/p/$postId',
      params: { author: 'studio', postId: 'first-post' },
      search: {},
    }),
  )
  await screen.findByRole('heading', { name: savedPost.title })
  await client.invalidateQueries({
    queryKey: mediaQuery('studio', {}).queryKey,
    refetchType: 'none',
  })
  const pending = deferredResponse()
  let reads = 0
  request.mockImplementation(async (input) => {
    if (input.includes('/media')) {
      reads++
      return pending.promise
    }
    return original(input)
  })
  let navigation!: Promise<void>
  act(() => {
    navigation = router.navigate({
      to: '/a/$author/media',
      params: { author: 'studio' },
      search: {},
    })
  })
  await waitFor(() => expect(reads).toBe(1))
  expect(document.querySelector('.author-pane[data-tab="posts"]')).toHaveAttribute('data-shown')
  expect(document.querySelector('.author-pane[data-tab="posts"]')).toHaveAttribute('inert')
  expect(document.querySelector('.author-pane[data-tab="media"]')).not.toHaveAttribute('data-shown')
  pending.resolve(Response.json(emptyMedia))
  await act(() => navigation)
  await waitFor(() =>
    expect(document.querySelector('.author-pane[data-tab="media"]')).toHaveAttribute('data-shown'),
  )
  unmount()
  client.clear()
})

test('a selected post remains readable when the parent post-list loader fails', async () => {
  const request = serve()
  const original = request.getMockImplementation()!
  request.mockImplementation(async (input) => {
    if (input.endsWith('/posts'))
      return Response.json(
        { error: { code: 'read_failed', message: 'List unavailable' } },
        { status: 503 },
      )
    return original(input)
  })
  const { client, unmount } = setup('/a/studio/p/first-post')
  expect(await screen.findByRole('heading', { name: savedPost.title })).toBeVisible()
  await waitFor(() =>
    expect(screen.getByRole('complementary', { name: 'Posts of Studio' })).toHaveTextContent(
      'List unavailable',
    ),
  )
  unmount()
  client.clear()
})

test('a pending next post hides stale controls while immediate favorite follows the new URL', async () => {
  const request = serve()
  const original = request.getMockImplementation()!
  const pending = deferredResponse()
  const write = deferredResponse()
  const writes: string[] = []
  request.mockImplementation(async (input) => {
    if (input.endsWith('/posts'))
      return Response.json({
        ...savedList,
        rows: [savedRow, { ...savedRow, id: 'next', title: 'Next post' }],
        total: 2,
      })
    if (input.endsWith('/posts/next')) return pending.promise
    if (input.endsWith('/marks')) {
      writes.push(input)
      return write.promise
    }
    return original(input)
  })
  const { client, router, unmount } = setup('/a/studio/p/first-post')
  await screen.findByRole('heading', { name: savedPost.title })
  let navigation!: Promise<void>
  act(() => {
    navigation = router.navigate({
      to: '/a/$author/p/$postId',
      params: { author: 'studio', postId: 'next' },
      search: {},
    })
  })
  await waitFor(() => expect(router.history.location.pathname).toBe('/a/studio/p/next'))
  await waitFor(() =>
    expect(screen.queryByRole('heading', { name: savedPost.title })).not.toBeInTheDocument(),
  )
  expect(screen.getByText('Loading post...')).toBeInTheDocument()
  fireEvent.keyDown(document, { code: 'KeyF', key: 'f' })
  await waitFor(() => expect(writes).toEqual(['/api/authors/studio/posts/next/marks']))
  pending.resolve(Response.json({ ...savedPost, id: 'next', title: 'Next post' }))
  await act(() => navigation)
  unmount()
  write.resolve(
    Response.json({ post: { ...savedPost, id: 'next', favorite: false }, author: savedAuthor }),
  )
  await waitFor(() => expect(client.isMutating()).toBe(0))
  client.clear()
})

test('first Posts visit after cached author history chooses the current newest post', async () => {
  const request = serve()
  const original = request.getMockImplementation()!
  const { client, router, unmount } = setup()
  await screen.findByRole('region', { name: 'Author media' })
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  await client.invalidateQueries({
    queryKey: postsQuery('studio', {}).queryKey,
    refetchType: 'none',
  })
  const fresh = {
    ...savedPost,
    id: 'newest',
    title: 'Newest post',
    created_at: '2026-02-02T00:00:00Z',
  }
  request.mockImplementation(async (input) => {
    if (input.endsWith('/posts'))
      return Response.json({ ...savedList, rows: [fresh, ...savedList.rows], total: 2 })
    if (input.endsWith('/posts/newest')) return Response.json(fresh)
    return original(input)
  })
  fireEvent.click(screen.getByRole('link', { name: 'Posts' }))
  await waitFor(() =>
    expect(document.querySelector('.author-pane[data-tab="posts"]')).toHaveAttribute('data-shown'),
  )
  expect(router.history.location.pathname).toBe('/a/studio/p/newest')
  unmount()
  client.clear()
})

test('fullscreen opening pushes once, arrows replace, Close returns to grid and Forward restores the last image', async () => {
  serve(photos)
  const { client, router, unmount } = setup(['/a/studio/p/first-post', '/a/studio/media'])
  await screen.findByRole('region', { name: 'Author media' })
  fireEvent.click(screen.getByRole('button', { name: 'Open one' }))
  await screen.findByRole('dialog', { name: 'Media viewer' })
  expect(router.history.location.state.__TSR_index).toBe(2)
  fireEvent.click(screen.getByRole('button', { name: 'Next media' }))
  await waitFor(() => expect(router.history.location.search).toBe('?open=two'))
  expect(router.history.location.state.__TSR_index).toBe(2)
  fireEvent.click(screen.getByRole('button', { name: 'Close media viewer' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(router.history.location.href).toBe('/a/studio/media')
  expect(router.history.location.state.__TSR_index).toBe(1)
  await act(async () => {
    router.history.forward()
  })
  await screen.findByRole('dialog', { name: 'Media viewer' })
  expect(router.history.location.search).toBe('?open=two')
  fireEvent.click(screen.getByRole('button', { name: 'Close media viewer' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await act(async () => {
    router.history.back()
  })
  await screen.findByRole('heading', { name: savedPost.title })
  expect(router.history.location.pathname).toBe('/a/studio/p/first-post')
  unmount()
  client.clear()
})

test('direct open link closes in place and post navigation clears the opening origin', async () => {
  serve(photos)
  const { client, router, unmount } = setup(['/a/studio/media?open=one'])
  await screen.findByRole('dialog', { name: 'Media viewer' })
  fireEvent.click(screen.getByRole('button', { name: 'Close media viewer' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(router.history.location.href).toBe('/a/studio/media')
  expect(router.history.location.state.__TSR_index).toBe(0)
  fireEvent.click(screen.getByRole('button', { name: 'Open two' }))
  await screen.findByRole('dialog', { name: 'Media viewer' })
  fireEvent.click(screen.getByRole('link', { name: savedPost.title }))
  await screen.findByRole('heading', { name: savedPost.title })
  expect(router.history.location.state.mediaViewerOrigin).toBeUndefined()
  fireEvent.click(screen.getByRole('link', { name: 'Media' }))
  await waitFor(() =>
    expect(document.querySelector('.author-pane[data-tab="media"]')).toHaveAttribute('data-shown'),
  )
  expect(router.history.location.search).toBe('')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  unmount()
  client.clear()
})

test('all five views keep only Media filters and a hidden toolbar cannot navigate', async () => {
  const request = serve()
  const { client, router, container, unmount } = setup(
    '/a/studio/media?fav=1&unseen=1&order=oldest',
  )
  await screen.findByRole('region', { name: 'Author media' })
  for (const name of ['Audio 0', 'Files 0', 'Photos 0', 'Videos 0', 'All 0']) {
    fireEvent.click(screen.getByRole('button', { name }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'true'),
    )
  }
  expect(Object.fromEntries(new URLSearchParams(router.history.location.search))).toEqual({
    fav: '1',
    order: 'oldest',
    unseen: '1',
  })
  expect(
    request.mock.calls.some(([input]) => input.includes('/media?') && input.includes('view=audio')),
  ).toBe(true)
  expect(
    request.mock.calls.some(([input]) => input.includes('/media?') && input.includes('view=files')),
  ).toBe(true)
  fireEvent.click(screen.getByRole('link', { name: 'Posts' }))
  await screen.findByRole('heading', { name: savedPost.title })
  expect(router.history.location.search).toBe('')
  const hidden = container.querySelector('.author-pane[data-tab="media"]')!
  fireEvent.click(hidden.querySelector('button')!)
  expect(router.history.location.pathname).toBe('/a/studio/p/first-post')
  unmount()
  client.clear()
})

test('hidden Media stops refetching and keeps its DOM after query eviction until a fresh return', async () => {
  const request = serve(photos)
  const { client, router, container, unmount } = setup()
  await screen.findByRole('button', { name: 'Open one' })
  const pane = container.querySelector('.author-pane[data-tab="media"]')!
  fireEvent.click(screen.getByRole('link', { name: 'Posts' }))
  await screen.findByRole('heading', { name: savedPost.title })
  const reads = () => request.mock.calls.filter(([input]) => input.includes('/media')).length
  const before = reads()
  await client.invalidateQueries({ queryKey: ['media', 'studio'] })
  expect(reads()).toBe(before)
  act(() => {
    client.removeQueries({ queryKey: ['media', 'studio'] })
  })
  expect(pane).toHaveTextContent('Open one')
  fireEvent.click(pane.querySelector('button')!)
  expect(router.history.location.pathname).toBe('/a/studio/p/first-post')
  fireEvent.click(screen.getByRole('link', { name: 'Media' }))
  await waitFor(() => expect(pane).toHaveAttribute('data-shown'))
  expect(container.querySelector('.author-pane[data-tab="media"]')).toBe(pane)
  expect(reads()).toBe(before + 1)
  unmount()
  client.clear()
})

test('direct Media hearts report a failed write without loading post details', async () => {
  const request = serve({ ...photos, items: photos.items.slice(0, 1) })
  const original = request.getMockImplementation()!
  request.mockImplementation(async (input) =>
    input.endsWith('/marks')
      ? Response.json(
          { error: { code: 'write_failed', message: 'Disk is full.' } },
          { status: 409 },
        )
      : original(input),
  )
  const { client, unmount } = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Remove from favorites' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Disk is full.')
  expect(
    request.mock.calls.some(
      ([input]) => input.includes('/posts/first-post') && !input.endsWith('/marks'),
    ),
  ).toBe(false)
  expect(screen.getByRole('button', { name: 'Remove from favorites' })).toBeEnabled()
  unmount()
  client.clear()
})

test('a locked Media post has its saved images but no heart', async () => {
  serve({
    ...photos,
    items: photos.items.slice(0, 1),
    posts: { [savedPost.id]: { ...savedMediaPost, access: 'locked' } },
  })
  const { client, unmount } = setup()
  expect(await screen.findByRole('button', { name: 'Open one' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: /favorites/ })).not.toBeInTheDocument()
  unmount()
  client.clear()
})

test('an active Media refresh failure retains its tiles and offers a working retry', async () => {
  const request = serve(photos)
  const original = request.getMockImplementation()!
  const { client, unmount } = setup()
  await screen.findByRole('button', { name: 'Open one' })
  let failing = true
  request.mockImplementation(async (input) =>
    input.includes('/media') && failing
      ? Response.json(
          { error: { code: 'read_failed', message: 'Media index unavailable.' } },
          { status: 503 },
        )
      : original(input),
  )
  await act(() => client.invalidateQueries({ queryKey: ['media', 'studio'] }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Media index unavailable.')
  expect(screen.getByRole('button', { name: 'Open one' })).toBeInTheDocument()
  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  unmount()
  client.clear()
})

test('an All audio tile starts the persistent player and the Authors link keeps the same audio element', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  const track = { ...savedVideo, kind: 'audio' as const, id: 'track', title: 'Track title' }
  const request = serve({ ...photos, items: [track] })
  const original = request.getMockImplementation()!
  request.mockImplementation(async (input) =>
    input === '/api/authors' ? Response.json([savedAuthor]) : original(input),
  )
  const { client, router, container, unmount } = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Open track' }))
  const player = await screen.findByRole('region', { name: 'Player' })
  expect(player).toHaveTextContent('Track title')
  const audio = container.querySelector('audio')!
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('link', { name: 'Authors' }))
  await screen.findByRole('heading', { name: 'Authors' })
  expect(router.history.location.pathname).toBe('/')
  expect(container.querySelector('audio')).toBe(audio)
  expect(player).toHaveTextContent('Track title')
  fireEvent.click(screen.getByRole('link', { name: savedAuthor.title }))
  await screen.findByRole('heading', { name: savedPost.title })
  expect(router.history.location.pathname).toBe('/a/studio/p/first-post')
  expect(container.querySelector('audio')).toBe(audio)
  expect(player).toHaveTextContent('Track title')
  unmount()
  client.clear()
})

test('returning to Favorites waits for a pending Posts write before revealing canonical Media', async () => {
  const request = serve(photos)
  const original = request.getMockImplementation()!
  const pending = deferredResponse()
  let favorite = true
  let mediaReads = 0
  request.mockImplementation(async (input) => {
    if (input.endsWith('/marks')) return pending.promise
    if (input.includes('/media')) {
      mediaReads++
      return Response.json(favorite ? photos : emptyMedia)
    }
    if (input.endsWith('/posts/first-post')) return Response.json({ ...savedPost, favorite })
    return original(input)
  })
  const { client, container, unmount } = setup('/a/studio/media?fav=1')
  await screen.findByRole('button', { name: 'Open one' })
  fireEvent.click(screen.getByRole('link', { name: 'Posts' }))
  const post = await screen.findByRole('region', { name: 'Selected post' })
  fireEvent.click(await within(post).findByRole('button', { name: 'Remove from favorites' }))
  await waitFor(() =>
    expect(request.mock.calls.some(([input]) => input.endsWith('/marks'))).toBe(true),
  )
  fireEvent.click(screen.getByRole('link', { name: 'Media' }))
  await waitFor(() =>
    expect(container.querySelector('.author-pane[data-tab="posts"]')).toHaveAttribute('inert'),
  )
  expect(container.querySelector('.author-pane[data-tab="posts"]')).toHaveAttribute('data-shown')
  expect(container.querySelector('.author-pane[data-tab="media"]')).not.toHaveAttribute(
    'data-shown',
  )
  expect(mediaReads).toBe(1)
  favorite = false
  pending.resolve(
    Response.json({ post: { ...savedRow, favorite }, author: { ...savedAuthor, favorites: 0 } }),
  )
  await waitFor(() =>
    expect(container.querySelector('.author-pane[data-tab="media"]')).toHaveAttribute('data-shown'),
  )
  expect(screen.getByText('No downloaded media in this view.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Open one' })).not.toBeInTheDocument()
  expect(mediaReads).toBe(2)
  unmount()
  client.clear()
})

test('a failed first Media load keeps the author tabs and recovers on retry', async () => {
  const request = serve(photos)
  const original = request.getMockImplementation()!
  let failing = true
  request.mockImplementation(async (input) =>
    input.includes('/media') && failing
      ? Response.json(
          { error: { code: 'read_failed', message: 'Media unavailable.' } },
          { status: 503 },
        )
      : original(input),
  )
  const { client, unmount } = setup()
  expect(await screen.findByRole('alert')).toHaveTextContent('Media unavailable.')
  expect(screen.getByRole('link', { name: 'Posts' })).toBeInTheDocument()
  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('button', { name: 'Open one' })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  unmount()
  client.clear()
})
