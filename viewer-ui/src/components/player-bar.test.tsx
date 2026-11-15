import { QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { PlayerBar } from '@/components/player-bar'
import { attachPostPlayback } from '@/lib/playback-controller'
import { saveMediaPosition } from '@/lib/playback-mutations'
import { createPlaybackActivity, writePlaybackPosition } from '@/lib/playback-writes'
import * as api from '@/lib/api'
import type { MediaItem, MediaPage } from '@/lib/api.gen'
import { NO_FILTERS } from '@/lib/filters'
import { pendingPlaybackMark } from '@/lib/playback-position'
import { createPlayerStore, currentTrack, PlayerProvider } from '@/lib/player'
import { createQueryClient } from '@/lib/queries'
import { playbackItem } from '@/test/playback-fixture'

const link = vi.hoisted(() => ({ searches: [] as unknown[] }))
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
    link.searches.push(search)
    return (
      <a href={`/a/${params.author}/p/${params.postId}`} className={className}>
        {children}
      </a>
    )
  },
}))

const tracks = [
  playbackItem({
    id: 'one',
    kind: 'audio',
    path: 'post/one.mp3',
    title: 'First track',
    position_s: 24,
  }),
  playbackItem({
    id: 'two',
    kind: 'audio',
    path: 'post/two.mp3',
    title: 'Removed track',
    position_s: 43,
    removed: true,
  }),
]
const page: MediaPage = {
  items: tracks,
  posts: {
    post: {
      access: 'open',
      title: 'Shared post',
      cover_path: 'post/cover.jpg',
      seen: false,
      favorite: false,
    },
  },
  missing: 0,
  counts: { all: 2, audio: 2, videos: 0, files: 0, images: 0 },
}

function metadata(audio: HTMLAudioElement, duration = 120): void {
  Object.defineProperty(audio, 'duration', { configurable: true, value: duration })
  Object.defineProperty(audio, 'readyState', { configurable: true, value: 1 })
  fireEvent.loadedMetadata(audio)
  fireEvent.durationChange(audio)
}

beforeEach(() => {
  link.searches.length = 0
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    this.currentTime = 0
    Object.defineProperty(this, 'readyState', { configurable: true, value: 0 })
    Object.defineProperty(this, 'duration', { configurable: true, value: Number.NaN })
  })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    Object.defineProperty(this, 'paused', { configurable: true, value: false })
    fireEvent.play(this)
    return Promise.resolve()
  })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    if (this.paused) return
    Object.defineProperty(this, 'paused', { configurable: true, value: true })
    fireEvent.pause(this)
  })
  vi.spyOn(api, 'savePlaybackPosition').mockImplementation(async (_author, id, position) => {
    const item = tracks.find((track) => track.id === id)
    if (!item) throw new Error('Unexpected media')
    return { ...item, ...pendingPlaybackMark(position), duration_s: position.duration }
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function setup(data = page) {
  const store = createPlayerStore()
  const client = createQueryClient()
  const tree = () => (
    <QueryClientProvider client={client}>
      <PlayerProvider store={store}>
        <PlayerBar />
      </PlayerProvider>
    </QueryClientProvider>
  )
  const view = render(tree())
  act(() => store.start('author', data, 'one'))
  const audio = view.container.querySelector<HTMLAudioElement>('audio')
  if (!audio) throw new Error('Expected persistent audio')
  return { ...view, store, client, audio, redraw: () => view.rerender(tree()) }
}

test('persistent audio resumes, survives rerenders, saves canonical positions and resumes Previous', async () => {
  const { audio, store, redraw, container, unmount, client } = setup()
  metadata(audio)
  expect(audio.currentTime).toBe(24)
  expect(screen.getByText('Resumed at 0:24')).toBeVisible()
  expect(link.searches.every((search) => search === NO_FILTERS)).toBe(true)
  audio.currentTime = 61
  fireEvent.timeUpdate(audio)
  redraw()
  expect(container.querySelector('audio')).toBe(audio)
  expect(audio.currentTime).toBe(61)
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  await waitFor(() => expect(store.getSnapshot()?.queue[0]?.position_s).toBe(61))
  expect(audio).toHaveAttribute('src', '/media/author/post/two.mp3')
  metadata(audio)
  expect(audio.currentTime).toBe(43)
  fireEvent.click(screen.getByRole('button', { name: 'Previous track' }))
  metadata(audio)
  expect(audio.currentTime).toBe(61)
  expect(container.querySelectorAll('audio')).toHaveLength(1)
  unmount()
  await waitFor(() => expect(client.isMutating()).toBe(0))
})

test('controls seek, change speed, start over, pause, resume and close', async () => {
  const { audio, store, client } = setup()
  metadata(audio)
  fireEvent.timeUpdate(audio)
  fireEvent.click(screen.getByRole('button', { name: 'Forward 15 seconds' }))
  expect(audio.currentTime).toBe(39)
  fireEvent.click(screen.getByRole('button', { name: 'Forward 15 seconds' }))
  expect(audio.currentTime).toBe(54)
  fireEvent.click(screen.getByRole('button', { name: 'Back 15 seconds' }))
  fireEvent.click(screen.getByRole('button', { name: 'Back 15 seconds' }))
  expect(audio.currentTime).toBe(24)
  fireEvent.change(screen.getByRole('slider', { name: 'Position' }), { target: { value: '70' } })
  expect(audio.currentTime).toBe(70)
  expect(screen.getByRole('slider', { name: 'Position' })).toHaveValue('70')
  fireEvent.change(screen.getByRole('slider', { name: 'Position' }), { target: { value: '0' } })
  expect(screen.getByRole('slider', { name: 'Position' })).toHaveValue('0')
  fireEvent.change(screen.getByRole('slider', { name: 'Position' }), { target: { value: '1' } })
  expect(screen.getByRole('slider', { name: 'Position' })).toHaveValue('1')
  expect(audio.currentTime).toBe(1)
  fireEvent.click(screen.getByRole('button', { name: 'Playback speed' }))
  expect(audio.playbackRate).toBe(1.25)
  fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
  expect(audio.currentTime).toBe(0)
  expect(screen.queryByText('Resumed at 0:24')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  expect(store.getSnapshot()?.playing).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Play' }))
  expect(store.getSnapshot()?.playing).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  expect(audio.playbackRate).toBe(1.25)
  fireEvent.click(screen.getByRole('button', { name: 'Close the player' }))
  expect(screen.queryByRole('region', { name: 'Player' })).not.toBeInTheDocument()
  expect(store.getSnapshot()).toBeNull()
  await waitFor(() => expect(client.isMutating()).toBe(0))
})

test('ended advances into removed tracks, finishes the last one and does not loop', async () => {
  const { audio, store, client } = setup()
  metadata(audio)
  audio.currentTime = 120
  fireEvent.ended(audio)
  expect(currentTrack(store.getSnapshot())?.id).toBe('two')
  await waitFor(() => expect(store.getSnapshot()?.queue[0]?.finished).toBe(true))
  metadata(audio)
  audio.currentTime = 120
  fireEvent.ended(audio)
  expect(currentTrack(store.getSnapshot())?.id).toBe('two')
  expect(store.getSnapshot()?.playing).toBe(false)
  await waitFor(() => expect(client.isMutating()).toBe(0))
})

test('broken tracks announce the error then advance once; manual navigation cancels their timer', async () => {
  vi.useFakeTimers()
  const { audio, store } = setup()
  fireEvent.error(audio)
  expect(screen.getByRole('status')).toHaveTextContent('Could not play this track.')
  await act(() => vi.advanceTimersByTimeAsync(1500))
  expect(currentTrack(store.getSnapshot())?.id).toBe('two')
  fireEvent.error(audio)
  fireEvent.click(screen.getByRole('button', { name: 'Previous track' }))
  await act(() => vi.advanceTimersByTimeAsync(1500))
  expect(currentTrack(store.getSnapshot())?.id).toBe('one')
  fireEvent.error(audio)
  fireEvent.click(screen.getByRole('button', { name: 'Close the player' }))
  await act(() => vi.advanceTimersByTimeAsync(1500))
  expect(store.getSnapshot()).toBeNull()
})

test('autoplay denial waits for a user and ignores stale rejected play requests', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValueOnce(
    new DOMException('Gesture required', 'NotAllowedError'),
  )
  const { audio, store } = setup()
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Press Play'))
  expect(currentTrack(store.getSnapshot())?.id).toBe('one')
  fireEvent.click(screen.getByRole('button', { name: 'Play' }))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(audio.paused).toBe(false)
})

test('aborted playback and an old rejected request do not fail a newer track', async () => {
  let reject: ((error: Error) => void) | undefined
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementationOnce(
    () =>
      new Promise<void>((_resolve, decline) => {
        reject = decline
      }),
  )
  const { store } = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  await act(async () => {
    reject?.(new Error('Old source failed'))
  })
  expect(currentTrack(store.getSnapshot())?.id).toBe('two')
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValueOnce(
    new DOMException('Source changed', 'AbortError'),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Previous track' }))
  await act(async () => {})
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('returning before a pending save finishes resumes its latest local position', async () => {
  let finish: ((item: MediaItem) => void) | undefined
  const delayed = new Promise<MediaItem>((resolve) => {
    finish = resolve
  })
  vi.mocked(api.savePlaybackPosition).mockImplementation(() => delayed)
  const { audio, store, client, unmount } = setup()
  metadata(audio)
  audio.currentTime = 65
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  fireEvent.click(screen.getByRole('button', { name: 'Previous track' }))
  metadata(audio)
  expect(audio.currentTime).toBe(65)
  expect(store.getSnapshot()?.queue[0]?.position_s).toBe(24)
  await act(async () => {
    finish?.({ ...tracks[0]!, position_s: 65 })
  })
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(store.getSnapshot()?.queue[0]?.position_s).toBe(65)
  unmount()
  await waitFor(() => expect(client.isMutating()).toBe(0))
})

test('playing a post video pauses the bar and its next play pauses the post video', async () => {
  const { audio, store, client } = setup()
  metadata(audio)
  audio.currentTime = 35
  const video = document.createElement('video')
  document.body.append(video)
  await act(() => video.play())
  expect(audio.paused).toBe(true)
  expect(store.getSnapshot()?.playing).toBe(false)
  await waitFor(() => expect(currentTrack(store.getSnapshot())?.position_s).toBe(35))
  fireEvent.click(screen.getByRole('button', { name: 'Play' }))
  expect(video.paused).toBe(true)
  video.remove()
  await waitFor(() => expect(client.isMutating()).toBe(0))
})

test('failed persistence stays visible and a later successful pause clears it', async () => {
  vi.mocked(api.savePlaybackPosition).mockRejectedValueOnce(new Error('Disk full'))
  const { audio, client } = setup({
    ...page,
    posts: { post: { ...page.posts.post!, cover_path: null } },
  })
  metadata(audio)
  audio.currentTime = 45
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  await waitFor(() =>
    expect(screen.getByRole('status')).toHaveTextContent('Playback position could not be saved.'),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Play' }))
  audio.currentTime = 46
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  await waitFor(() =>
    expect(screen.queryByText('Playback position could not be saved.')).not.toBeInTheDocument(),
  )
  await waitFor(() => expect(client.isMutating()).toBe(0))
})

test('late save responses update their original track without changing the current request', async () => {
  let finish: ((item: MediaItem) => void) | undefined
  const delayed = new Promise<MediaItem>((resolve) => {
    finish = resolve
  })
  vi.mocked(api.savePlaybackPosition).mockImplementation(() => delayed)
  const { audio, store } = setup()
  metadata(audio)
  audio.currentTime = 62
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  const request = store.getSnapshot()?.request
  await waitFor(() => expect(finish).toBeDefined())
  await act(async () => {
    finish?.({ ...tracks[0]!, position_s: 63 })
  })
  expect(currentTrack(store.getSnapshot())?.id).toBe('two')
  expect(store.getSnapshot()?.queue[0]?.position_s).toBe(63)
  expect(store.getSnapshot()?.request).toBe(request)
})

test('a delayed old-author save cannot rewrite a replacement author queue', async () => {
  let resolve!: (item: MediaItem) => void
  const saving = new Promise<MediaItem>((done) => {
    resolve = done
  })
  vi.mocked(api.savePlaybackPosition).mockImplementation(() => saving)
  const { store, audio, client, container } = setup()
  metadata(audio)
  audio.currentTime = 57
  act(() => store.start('another-author', page, 'two'))
  expect(container.querySelector('audio')).toBe(audio)
  expect(audio).toHaveAttribute('src', '/media/another-author/post/two.mp3')
  const snapshot = store.getSnapshot()
  await act(async () => {
    resolve({ ...tracks[0]!, position_s: 57 })
  })
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(store.getSnapshot()).toBe(snapshot)
  expect(store.getSnapshot()?.queue[0]?.position_s).toBe(24)
})

test('failed final track does not loop or repeat loads, and autoplay rejection never advances', async () => {
  vi.useFakeTimers()
  const { store, audio } = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  const request = store.getSnapshot()?.request
  const load = vi.spyOn(HTMLMediaElement.prototype, 'load')
  const loads = load.mock.calls.length
  fireEvent.error(audio)
  await act(() => vi.advanceTimersByTimeAsync(20_000))
  expect(store.getSnapshot()?.request).toBe(request)
  expect(load).toHaveBeenCalledTimes(loads)
  expect(screen.getByRole('status')).toHaveTextContent('Could not play this track.')
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValueOnce(
    new DOMException('Gesture', 'NotAllowedError'),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Previous track' }))
  await act(() => vi.advanceTimersByTimeAsync(20_000))
  expect(currentTrack(store.getSnapshot())?.id).toBe('one')
  expect(screen.getByRole('status')).toHaveTextContent('Press Play')
})

test('repeated close/reopen and rapid next/previous keep the newest unsaved local position', async () => {
  let resolve!: (item: MediaItem) => void
  const saving = new Promise<MediaItem>((done) => {
    resolve = done
  })
  vi.mocked(api.savePlaybackPosition).mockImplementation(() => saving)
  const { store, audio, client, container } = setup()
  metadata(audio)
  audio.currentTime = 79
  fireEvent.click(screen.getByRole('button', { name: 'Close the player' }))
  expect(container.querySelector('audio')).toBeNull()
  act(() => store.start('author', page, 'one'))
  const reopened = container.querySelector<HTMLAudioElement>('audio')!
  metadata(reopened)
  expect(reopened.currentTime).toBe(79)
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  fireEvent.click(screen.getByRole('button', { name: 'Previous track' }))
  metadata(reopened)
  expect(reopened.currentTime).toBe(79)
  await act(async () => {
    resolve({ ...tracks[0]!, position_s: 79 })
  })
  await waitFor(() => expect(client.isMutating()).toBe(0))
})

function postTrack(client: ReturnType<typeof createQueryClient>) {
  const audio = document.createElement('audio')
  audio.src = '/media/author/post/one.mp3'
  document.body.append(audio)
  metadata(audio)
  const identity = {
    origin: window.location.origin,
    author: 'author',
    postId: 'post',
    mediaId: 'one',
  }
  const detach = attachPostPlayback(
    audio,
    tracks[0]!,
    (item, position) =>
      writePlaybackPosition(identity, item, position, async (saved, value, options) => {
        await saveMediaPosition(client, 'author', 'post', saved, value, options.keepalive)
      }),
    undefined,
    createPlaybackActivity(identity),
  )
  return {
    audio,
    cleanup: () => {
      detach()
      audio.remove()
    },
  }
}

test('a paused bar cannot overwrite a newer position saved by the same track in a post', async () => {
  const { audio, store, client } = setup()
  metadata(audio)
  audio.currentTime = 35
  const post = postTrack(client)
  await act(() => post.audio.play())
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(audio.paused).toBe(true)
  post.audio.currentTime = 75
  act(() => post.audio.pause())
  await waitFor(() => expect(client.isMutating()).toBe(0))
  const save = vi.mocked(api.savePlaybackPosition)
  save.mockClear()
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(save.mock.calls.filter(([, id]) => id === 'one')).toEqual([])
  expect(store.getSnapshot()?.queue[0]?.position_s).toBe(75)
  post.cleanup()
})

test('a failed old pause is superseded by a later successful position from the post player', async () => {
  vi.mocked(api.savePlaybackPosition).mockRejectedValueOnce(new Error('Temporary save failure'))
  const { audio, client, store } = setup()
  metadata(audio)
  audio.currentTime = 35
  const post = postTrack(client)
  await act(() => post.audio.play())
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(screen.getByRole('status')).toHaveTextContent('Playback position could not be saved.')
  post.audio.currentTime = 75
  act(() => post.audio.pause())
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(store.getSnapshot()?.queue[0]?.position_s).toBe(75)
  const save = vi.mocked(api.savePlaybackPosition)
  save.mockClear()
  fireEvent.click(screen.getByRole('button', { name: 'Next track' }))
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(save.mock.calls.filter(([, id]) => id === 'one')).toEqual([])
  expect(store.getSnapshot()?.queue[0]?.position_s).toBe(75)
  post.cleanup()
})

test('a failed pause at the same position retries on pagehide without new playback', async () => {
  vi.mocked(api.savePlaybackPosition).mockRejectedValueOnce(new Error('Temporary save failure'))
  const { audio, client, store } = setup()
  metadata(audio)
  audio.currentTime = 35
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(screen.getByRole('status')).toHaveTextContent('Playback position could not be saved.')
  fireEvent(window, new Event('pagehide'))
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(store.getSnapshot()?.queue[0]?.position_s).toBe(35)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test.each([
  { filename: 'Recording.mp3', label: 'Recording.mp3' },
  { filename: null, label: 'Untitled track' },
])(
  'missing track metadata keeps $label and a safe seek range before duration loads',
  ({ filename, label }) => {
    const unknown = {
      ...tracks[0]!,
      title: null,
      filename,
      duration_s: null,
      position_s: null,
    }
    const data = {
      ...page,
      items: [unknown],
      posts: { post: { ...page.posts.post!, title: '', cover_path: null } },
    }
    const { audio } = setup(data)
    expect(screen.getByText(label)).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open post' })).toHaveAttribute(
      'href',
      '/a/author/p/post',
    )
    expect(screen.getByRole('slider', { name: 'Position' })).toHaveAttribute('max', '0')
    fireEvent.click(screen.getByRole('button', { name: 'Forward 15 seconds' }))
    expect(audio.currentTime).toBe(0)
    fireEvent.durationChange(audio)
    expect(screen.getByRole('slider', { name: 'Position' })).toHaveValue('0')
  },
)
