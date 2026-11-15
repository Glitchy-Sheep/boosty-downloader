import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState, type ReactNode } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { AudioList } from '@/components/audio-list'
import { FileList } from '@/components/file-list'
import type { MediaItem, MediaPage } from '@/lib/api.gen'
import { NO_FILTERS } from '@/lib/filters'
import { createPlayerStore, currentTrack, PlayerProvider, type PlayerStore } from '@/lib/player'
import { playbackItem } from '@/test/playback-fixture'

const marks = vi.hoisted(() => ({ pending: false, error: null as string | null, toggle: vi.fn() }))
const links = vi.hoisted(() => ({ searches: [] as unknown[] }))
vi.mock('@/hooks/use-favorite', () => ({ useFavorite: () => marks }))
vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    params,
    search,
    className,
  }: {
    children: ReactNode
    params: { author: string; postId: string }
    search: unknown
    className: string
  }) => {
    links.searches.push(search)
    return (
      <a href={`/a/${params.author}/p/${params.postId}`} className={className}>
        {children}
      </a>
    )
  },
}))

function page(items: MediaItem[], missing = 0): MediaPage {
  return {
    items,
    missing,
    counts: { all: 0, audio: 0, videos: 0, images: 0, files: items.length },
    posts: {
      post: {
        access: 'open',
        title: 'Shared post',
        seen: false,
        favorite: false,
        cover_path: 'post/cover.jpg',
      },
    },
  }
}

beforeEach(() => {
  marks.error = null
  marks.pending = false
  marks.toggle.mockClear()
  links.searches.length = 0
  vi.stubGlobal(
    'ResizeObserver',
    class implements ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(400)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
    new DOMRect(0, 0, 800, 400),
  )
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function Harness({
  data,
  store,
  audio = true,
  active = true,
  listKey = 'all',
}: {
  data: MediaPage
  store: PlayerStore
  audio?: boolean
  active?: boolean
  listKey?: string
}) {
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null)
  const List = audio ? AudioList : FileList
  return (
    <PlayerProvider store={store}>
      <div ref={setScroller} data-testid="scroller">
        <List author="a !#" page={data} active={active} scroller={scroller} listKey={listKey} />
      </div>
    </PlayerProvider>
  )
}

test('audio shows artist, dates, played part, post heart and plays current filtered queue including removed', async () => {
  const items = [
    playbackItem({
      id: 'one',
      kind: 'audio',
      title: 'First song',
      artist: 'Artist',
      position_s: 60,
    }),
    playbackItem({
      id: 'two',
      kind: 'audio',
      title: 'Removed song',
      removed: true,
      finished: true,
    }),
  ]
  const data = page(items, 2)
  const store = createPlayerStore()
  const { container } = render(<Harness data={data} store={store} />)
  await waitFor(() => expect(screen.getByText('Artist')).toBeVisible())
  expect(screen.getAllByText(/1 Nov 2026/)[0]).toBeDefined()
  expect(screen.getByTitle('50% played')).toBeInTheDocument()
  expect(screen.getByLabelText('Played to the end')).toBeInTheDocument()
  const missing = container.querySelector('[data-missing-note]')
  const heading = container.querySelector('[data-removed-heading]')
  expect(missing?.compareDocumentPosition(heading!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  fireEvent.click(screen.getByRole('button', { name: 'Play First song' }))
  expect(store.getSnapshot()?.queue).toEqual(items)
  act(() => {
    store.step(1)
    store.setPlaying(true)
  })
  expect(currentTrack(store.getSnapshot())?.id).toBe('two')
  expect(container.querySelector('[data-playing]')).not.toBeNull()
  expect(container.querySelector('[data-playing] [data-art]')).not.toHaveClass('opacity-35')
  fireEvent.click(screen.getAllByRole('button', { name: 'Add to favorites' })[0]!)
  expect(marks.toggle).toHaveBeenCalledOnce()
  expect(links.searches.every((search) => search === NO_FILTERS)).toBe(true)
})

test.each([null, '   '])(
  'audio with title=%s and no saved progress can play and pause the current queue without restarting it',
  async (title) => {
    const store = createPlayerStore()
    const item = playbackItem({ kind: 'audio', title, position_s: null, artist: null })
    const data = page([item])
    data.posts.post = { ...data.posts.post!, title: '', cover_path: null }
    const element = document.createElement('audio')
    const play = vi.spyOn(element, 'play').mockImplementation(async () => {
      store.setPlaying(true)
    })
    const pause = vi.spyOn(element, 'pause').mockImplementation(() => {
      store.setPlaying(false)
    })
    store.start('a !#', data, item.id)
    store.attach(element)
    const initialRequest = store.getSnapshot()?.request
    render(<Harness data={data} store={store} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Play Untitled track' }))
    await waitFor(() => expect(play).toHaveBeenCalledOnce())
    expect(screen.getByTitle('0% played')).toBeInTheDocument()
    Object.defineProperty(element, 'paused', { value: false })
    fireEvent.click(screen.getByRole('button', { name: 'Pause Untitled track' }))
    expect(pause).toHaveBeenCalledOnce()
    expect(store.getSnapshot()?.request).toBe(initialRequest)
    store.attach(null)
  },
)

test('locked audio omits heart, removed-only lists have no rule, and fallback cover is dimmed', async () => {
  const item = playbackItem({
    kind: 'audio',
    title: null,
    removed: true,
    artist: null,
    duration_s: null,
  })
  const data = page([item])
  data.posts.post = { ...data.posts.post!, access: 'locked', cover_path: null }
  const { container } = render(<Harness data={data} store={createPlayerStore()} />)
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Play Shared post, removed by the author' }),
    ).toBeVisible(),
  )
  expect(screen.queryByRole('button', { name: 'Add to favorites' })).not.toBeInTheDocument()
  expect(container.querySelector('[data-removed-heading] .border-t')).toBeNull()
  expect(container.querySelector('[data-art]')).toHaveClass('opacity-35')
})

test('audio retains scroll while hidden, ignores starts while inactive, resets for new filters and reports favorite failures visibly', async () => {
  const data = page([playbackItem({ kind: 'audio', title: 'Song' })])
  const store = createPlayerStore()
  const { rerender } = render(<Harness data={data} store={store} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Play Song' })).toBeVisible())
  const scroller = screen.getByTestId('scroller')
  scroller.scrollTop = 50
  rerender(<Harness data={data} store={store} active={false} />)
  expect(scroller.scrollTop).toBe(50)
  fireEvent.click(screen.getByRole('button', { name: 'Play Song', hidden: true }))
  expect(store.getSnapshot()).toBeNull()
  expect(screen.getByRole('button', { name: 'Add to favorites', hidden: true })).toBeDisabled()
  marks.error = 'Favorite could not be saved.'
  rerender(<Harness data={data} store={store} listKey="fav" />)
  expect(scroller.scrollTop).toBe(0)
  expect(screen.getByRole('status')).toBeVisible()
  expect(screen.getByRole('status')).toHaveTextContent(marks.error)
})

test('files provide encoded downloads and post links without row actions, and no heading rule', async () => {
  const files = [
    playbackItem({ kind: 'files', filename: 'A file !#.pdf', path: 'post/A file !#.pdf' }),
    playbackItem({
      id: 'removed',
      kind: 'files',
      filename: null,
      path: 'post/retained.zip',
      removed: true,
    }),
  ]
  const { container } = render(
    <Harness data={page(files, 1)} store={createPlayerStore()} audio={false} />,
  )
  const download = await screen.findByRole('link', { name: 'Download A file !#.pdf' })
  expect(download).toHaveAttribute('href', '/media/a%20%21%23/post/A%20file%20%21%23.pdf')
  expect(download).toHaveAttribute('download', 'A file !#.pdf')
  expect(
    screen.getByRole('link', { name: 'Download retained.zip, removed by the author' }),
  ).toHaveAttribute('download', 'retained.zip')
  expect(screen.getAllByText('100 B')).toHaveLength(2)
  expect(container.querySelector('[data-removed-heading] .border-t')).toBeNull()
  expect(
    container
      .querySelector('[data-missing-note]')
      ?.compareDocumentPosition(container.querySelector('[data-removed-heading]')!),
  ).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  expect(container.querySelector('[data-removed] [data-art]')).toHaveClass('opacity-70')
  expect(links.searches.every((search) => search === NO_FILTERS)).toBe(true)
})

test('thousands of file rows keep a bounded DOM', async () => {
  const data = page(
    Array.from({ length: 2000 }, (_, index) =>
      playbackItem({ kind: 'files', id: `file-${index}` }),
    ),
  )
  const { container } = render(<Harness data={data} store={createPlayerStore()} audio={false} />)
  await waitFor(() =>
    expect(container.querySelectorAll('[data-media-id]').length).toBeGreaterThan(0),
  )
  expect(container.querySelectorAll('[data-media-id]').length).toBeLessThan(100)
})
