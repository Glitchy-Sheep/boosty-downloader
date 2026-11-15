import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { MediaViewer } from '@/components/media-viewer'
import * as api from '@/lib/api'
import type { MediaItem, MediaPage } from '@/lib/api.gen'
import { createQueryClient } from '@/lib/queries'
import { savedRow, savedVideo } from '@/test/post-fixtures'

const marks = vi.hoisted(() => ({ pending: false, error: null as string | null, toggle: vi.fn() }))
vi.mock('@/hooks/use-favorite', () => ({ useFavorite: () => marks }))

const photo = (id: string, changes: Partial<MediaItem> = {}): MediaItem => ({
  ...savedVideo,
  id,
  kind: 'images',
  file_type: 'image',
  path: `post/${id} !'() #.jpg`,
  filename: `${id}.jpg`,
  title: id,
  duration_s: null,
  position_s: null,
  ...changes,
})

function page(items: MediaItem[]): MediaPage {
  return {
    items,
    posts: {
      [savedRow.id]: {
        title: savedRow.title,
        favorite: true,
        seen: false,
        cover_path: null,
        access: 'open',
      },
    },
    missing: 0,
    counts: { all: items.length, images: items.length, videos: 0, audio: 0, files: 0 },
  }
}

const defaults = () => ({
  author: 'studio',
  data: page([photo('one'), photo('two', { removed: true }), photo('three')]),
  openId: 'one' as string | undefined,
  active: true,
  onShow: vi.fn(),
  onClose: vi.fn(),
  onRestoreFocus: vi.fn(async (_id: string) => true),
  postHref: (id: string) => `/a/studio/p/${id}`,
  onPost: vi.fn(),
})

function setup(props = defaults()) {
  const client = createQueryClient()
  const tree = (current: ReturnType<typeof defaults>) => (
    <QueryClientProvider client={client}>
      <MediaViewer {...current} />
    </QueryClientProvider>
  )
  const view = render(tree(props))
  return {
    ...view,
    client,
    props,
    rerender: (current: ReturnType<typeof defaults>) => view.rerender(tree(current)),
  }
}

beforeEach(() => {
  marks.pending = false
  marks.error = null
  marks.toggle.mockClear()
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

test('shows canonical photo order, skips nonvisual items, preloads neighbors and keeps the dialog focused', async () => {
  const originalImage = window.Image
  const preload: HTMLImageElement[] = []
  vi.spyOn(window, 'Image').mockImplementation(function () {
    const image = new originalImage()
    preload.push(image)
    return image
  })
  const props = defaults()
  props.data.items.splice(1, 0, { ...savedVideo, id: 'audio', kind: 'audio' })
  const view = setup(props)
  const dialog = screen.getByRole('dialog', { name: 'Media viewer' })
  expect(dialog).toHaveFocus()
  expect(within(dialog).getByText('1 / 3')).toBeInTheDocument()
  expect(within(dialog).getByRole('img', { name: 'one' })).toHaveAttribute(
    'src',
    '/media/studio/post/one%20%21%27%28%29%20%23.jpg',
  )
  expect(preload.at(-1)?.src).toContain('two%20%21%27%28%29%20%23.jpg')
  expect(screen.queryByRole('button', { name: 'Previous media' })).not.toBeInTheDocument()
  fireEvent.keyDown(dialog, { key: 'ArrowRight' })
  expect(props.onShow).toHaveBeenLastCalledWith('two')
  view.rerender({ ...props, openId: 'two' })
  expect(screen.getByText('2 / 3')).toBeInTheDocument()
  expect(screen.getByText(/Removed by the author/)).toBeInTheDocument()
  expect(document.activeElement).toBe(dialog)
  fireEvent.click(screen.getByRole('button', { name: 'Previous media' }))
  expect(props.onShow).toHaveBeenLastCalledWith('one')
  fireEvent.click(screen.getByRole('button', { name: 'Next media' }))
  expect(props.onShow).toHaveBeenLastCalledWith('three')
  fireEvent.keyDown(dialog, { key: 'ArrowLeft' })
  expect(props.onShow).toHaveBeenLastCalledWith('one')
  const calls = props.onShow.mock.calls.length
  fireEvent.keyDown(dialog, { key: 'ArrowRight', ctrlKey: true })
  fireEvent.keyDown(dialog, { key: 'j' })
  expect(props.onShow).toHaveBeenCalledTimes(calls)
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(props.onClose).toHaveBeenCalledOnce()
  view.rerender({ ...props, openId: undefined })
  await waitFor(() => expect(props.onRestoreFocus).toHaveBeenCalledWith('two'))
  view.unmount()
  view.client.clear()
})

test('preserves modified post links and shows the shared heart pending/error state', () => {
  const view = setup()
  const link = screen.getByRole('link', { name: savedRow.title })
  expect(link).toHaveAttribute('href', `/a/studio/p/${savedRow.id}`)
  const browserDefault = vi.fn((event: Event) => {
    expect(event.defaultPrevented).toBe(false)
    event.preventDefault()
  })
  document.addEventListener('click', browserDefault, { once: true })
  fireEvent.click(link, { ctrlKey: true })
  expect(browserDefault).toHaveBeenCalledOnce()
  expect(view.props.onPost).not.toHaveBeenCalled()
  fireEvent.click(link)
  expect(view.props.onPost).toHaveBeenCalledWith(savedRow.id)
  fireEvent.click(screen.getByRole('button', { name: 'Remove from favorites' }))
  expect(marks.toggle).toHaveBeenCalledOnce()
  marks.pending = true
  marks.error = 'Favorite could not be saved.'
  view.rerender({ ...view.props })
  expect(screen.getByRole('button', { name: 'Remove from favorites' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent(marks.error)
  fireEvent.click(screen.getByRole('button', { name: 'Close media viewer' }))
  expect(view.props.onClose).toHaveBeenCalledOnce()
  view.unmount()
  view.client.clear()
})

test('locked media stay readable without a heart and untitled posts have a useful link', () => {
  const props = defaults()
  props.data.posts[savedRow.id] = {
    title: ' ',
    favorite: true,
    seen: true,
    cover_path: null,
    access: 'locked',
  }
  const view = setup(props)
  expect(screen.getByRole('link', { name: 'Untitled post' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /favorites/ })).not.toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'one' })).toBeInTheDocument()
  view.unmount()
  view.client.clear()
})

test('unknown pieces and missing post records do not open a dialog', () => {
  const props = defaults()
  const view = setup({ ...props, openId: 'missing' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  view.rerender({ ...props, data: { ...props.data, posts: {} } })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  view.unmount()
  view.client.clear()
})

test('deactivating the Media tab closes its portal without navigating or focusing hidden tiles', async () => {
  const view = setup()
  view.rerender({ ...view.props, active: false })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
  expect(view.props.onClose).not.toHaveBeenCalled()
  expect(view.props.onRestoreFocus).not.toHaveBeenCalled()
  view.rerender({ ...view.props, active: true })
  expect(screen.getByRole('dialog')).toHaveFocus()
  view.unmount()
  view.client.clear()
})

test('a video resumes with Start over, keeps seeking keys, preserves its element and saves on close', async () => {
  const save = vi
    .spyOn(api, 'savePlaybackPosition')
    .mockImplementation(async (_author, _id, position) => ({
      ...savedVideo,
      position_s: position.seconds,
      duration_s: position.duration,
    }))
  const props = defaults()
  props.data = page([photo('one'), savedVideo, photo('three')])
  props.openId = savedVideo.id
  const view = setup(props)
  const video = screen.getByLabelText('Saved video') as HTMLVideoElement
  Object.defineProperties(video, {
    duration: { configurable: true, value: 100 },
    readyState: { configurable: true, value: 1 },
    paused: { configurable: true, value: true },
  })
  fireEvent.loadedMetadata(video)
  expect(video.currentTime).toBe(20)
  expect(screen.getByText('Resumed at 0:20')).toBeInTheDocument()
  fireEvent.keyDown(video, { key: 'ArrowRight' })
  expect(props.onShow).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
  expect(video.currentTime).toBe(0)
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith('studio', savedVideo.id, { seconds: 0, duration: 100 }, true),
  )
  view.rerender({
    ...props,
    data: {
      ...props.data,
      posts: { [savedRow.id]: { ...props.data.posts[savedRow.id]!, favorite: false } },
    },
  })
  expect(screen.getByLabelText('Saved video')).toBe(video)
  video.currentTime = 36
  fireEvent.play(video)
  view.rerender({ ...props, openId: undefined })
  await waitFor(() =>
    expect(save).toHaveBeenLastCalledWith(
      'studio',
      savedVideo.id,
      { seconds: 36, duration: 100 },
      true,
    ),
  )
  await waitFor(() => expect(props.onRestoreFocus).toHaveBeenCalledWith(savedVideo.id))
  view.unmount()
  view.client.clear()
})

test('autoplay refusal keeps native controls and a failed position save stays visible until a retry', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
    new DOMException('Not allowed', 'NotAllowedError'),
  )
  const save = vi
    .spyOn(api, 'savePlaybackPosition')
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue({ ...savedVideo, position_s: 30 })
  const props = defaults()
  props.data = page([{ ...savedVideo, title: null, filename: null }])
  props.openId = savedVideo.id
  const view = setup(props)
  const video = screen.getByLabelText('Saved video') as HTMLVideoElement
  expect(video).toHaveAttribute('controls')
  Object.defineProperties(video, {
    duration: { configurable: true, value: 100 },
    readyState: { configurable: true, value: 1 },
    paused: { configurable: true, value: true },
  })
  fireEvent.loadedMetadata(video)
  video.currentTime = 30
  fireEvent.play(video)
  fireEvent.pause(video)
  await waitFor(() =>
    expect(screen.getByRole('status')).toHaveTextContent('Playback position could not be saved.'),
  )
  fireEvent.pause(video)
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  expect(save).toHaveBeenCalledTimes(2)
  view.unmount()
  await act(() => Promise.resolve())
  view.client.clear()
})

test('the final photo has no forward action and close tolerates a tile removed from the grid', async () => {
  const props = defaults()
  props.openId = 'three'
  props.data.posts[savedRow.id]!.title = ''
  props.data.items[2]!.title = null
  props.onRestoreFocus.mockRejectedValueOnce(new Error('Grid has left the page'))
  const view = setup(props)
  expect(screen.getByRole('img', { name: 'Saved image' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Next media' })).not.toBeInTheDocument()
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'ArrowRight' })
  expect(props.onShow).not.toHaveBeenCalled()
  view.rerender({ ...props, openId: undefined })
  await waitFor(() => expect(props.onRestoreFocus).toHaveBeenCalledWith('three'))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  view.unmount()
  view.client.clear()
})
