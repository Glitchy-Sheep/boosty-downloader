import { act, fireEvent, render, screen } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MediaItem } from '@/lib/api.gen'
import { usePostPlayback, type SavePosition } from '@/hooks/use-post-playback'
import { deferred, playbackItem, setPlaying } from '@/test/playback-fixture'

const html = '<p>Text</p><video controls><source src="/media/author/post/video.mp4"></video>'

function Body({ item, save, author = 'author', markup = html }: { item: MediaItem; save: SavePosition; author?: string; markup?: string }) {
  const rootRef = useRef<HTMLDivElement>(null)
  usePostPlayback({ rootRef, author, postId: item.post_id, html: markup, media: [item], savePosition: save })
  return <div ref={rootRef} dangerouslySetInnerHTML={{ __html: markup }} />
}

function metadata(element: HTMLMediaElement): void {
  Object.defineProperties(element, {
    duration: { configurable: true, value: 120 },
    readyState: { configurable: true, value: 1 },
    paused: { configurable: true, value: true, writable: true },
  })
  fireEvent.loadedMetadata(element)
}

afterEach(() => vi.restoreAllMocks())

describe('usePostPlayback', () => {
  it.each([
    { action: 'pause', expected: 40 },
    { action: 'start over', expected: 0 },
    { action: 'finish', expected: 0 },
  ])('resumes the newest queued state after a rapid return following $action', async ({ action, expected }) => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    const pending = deferred()
    const save = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(undefined)
    const first = render(<Body item={playbackItem()} save={save} />)
    const video = first.container.querySelector('video')!
    metadata(video)
    setPlaying(video)
    video.currentTime = 40
    fireEvent.pause(video)
    await act(() => Promise.resolve())
    if (action === 'start over') fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
    if (action === 'finish') {
      video.currentTime = 120
      fireEvent.ended(video)
    }
    first.unmount()
    const second = render(<Body item={playbackItem()} save={save} />)
    const returned = second.container.querySelector('video')!
    metadata(returned)
    const observed = returned.currentTime
    second.unmount()
    await act(async () => { pending.resolve(); await pending.promise })
    expect(observed).toBe(expected)
  })

  it('uses queued partial playback over an older server-confirmed finished mark', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    const pending = deferred()
    const save = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(undefined)
    const item = playbackItem({ finished: true, position_s: 0 })
    const first = render(<Body item={item} save={save} />)
    const video = first.container.querySelector('video')!
    metadata(video)
    setPlaying(video)
    video.currentTime = 40
    fireEvent.pause(video)
    await act(() => Promise.resolve())
    first.unmount()
    const second = render(<Body item={item} save={save} />)
    const returned = second.container.querySelector('video')!
    metadata(returned)
    const observed = returned.currentTime
    second.unmount()
    await act(async () => { pending.resolve(); await pending.promise })
    expect(observed).toBe(40)
  })

  it('keeps a newer queued resume point when an older response updates the detail cache', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    const older = deferred()
    const newer = deferred()
    const save = vi.fn().mockReturnValueOnce(older.promise).mockReturnValue(newer.promise)
    const first = render(<Body item={playbackItem()} save={save} />)
    const video = first.container.querySelector('video')!
    metadata(video)
    setPlaying(video)
    video.currentTime = 20
    fireEvent.pause(video)
    await act(() => Promise.resolve())
    video.currentTime = 40
    fireEvent.pause(video)
    first.unmount()
    await act(async () => { older.resolve(); await older.promise })
    const second = render(<Body item={playbackItem({ position_s: 20 })} save={save} />)
    const returned = second.container.querySelector('video')!
    metadata(returned)
    const observed = returned.currentTime
    second.unmount()
    await act(async () => { newer.resolve(); await newer.promise })
    expect(observed).toBe(40)
  })

  it('shows a pending save failure on the returned view and then falls back to confirmed marks', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    const pending = deferred()
    const save = vi.fn().mockReturnValue(pending.promise)
    const first = render(<Body item={playbackItem()} save={save} />)
    const video = first.container.querySelector('video')!
    metadata(video)
    setPlaying(video)
    video.currentTime = 40
    fireEvent.pause(video)
    await act(() => Promise.resolve())
    first.unmount()
    const second = render(<Body item={playbackItem()} save={save} />)
    metadata(second.container.querySelector('video')!)
    await act(async () => {
      pending.reject(new Error('offline'))
      await pending.promise.catch(() => undefined)
    })
    expect(screen.getByRole('status')).toHaveTextContent('Playback position could not be saved.')
    second.unmount()
    const third = render(<Body item={playbackItem()} save={save} />)
    const returned = third.container.querySelector('video')!
    metadata(returned)
    expect(returned.currentTime).toBe(12)
    third.unmount()
  })

  it('keeps players and resume position stable when only cached marks and callbacks change', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    const oldSave = vi.fn().mockResolvedValue(undefined)
    const newSave = vi.fn().mockResolvedValue(undefined)
    const { container, rerender, unmount } = render(<Body item={playbackItem()} save={oldSave} />)
    const video = container.querySelector('video')!
    metadata(video)
    expect(video.currentTime).toBe(12)
    setPlaying(video)
    video.currentTime = 30
    rerender(<Body item={playbackItem({ position_s: 24 })} save={newSave} />)
    expect(container.querySelector('video')).toBe(video)
    expect(video.currentTime).toBe(30)
    expect(video.pause).not.toHaveBeenCalled()
    expect(container.querySelectorAll('.resume-note')).toHaveLength(1)
    fireEvent.pause(video)
    await act(() => Promise.resolve())
    expect(oldSave).not.toHaveBeenCalled()
    expect(newSave).toHaveBeenCalledWith(expect.anything(), { seconds: 30, duration: 120 }, { keepalive: true })
    unmount()
  })

  it('retains the old identity for queued cleanup after the selected post changes', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    const pending = deferred()
    const oldSave = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(undefined)
    const newSave = vi.fn().mockResolvedValue(undefined)
    const { container, rerender, unmount } = render(<Body item={playbackItem()} save={oldSave} />)
    const video = container.querySelector('video')!
    metadata(video)
    setPlaying(video)
    video.currentTime = 25
    fireEvent.pause(video)
    await act(() => Promise.resolve())
    video.currentTime = 30
    const other = playbackItem({ id: 'other-media', post_id: 'other', path: 'other/video.mp4' })
    rerender(<Body item={other} save={newSave} markup={html.replaceAll('/post/', '/other/')} />)
    expect(oldSave).toHaveBeenCalledTimes(1)
    expect(newSave).not.toHaveBeenCalled()
    await act(async () => { pending.resolve(); await pending.promise })
    expect(oldSave).toHaveBeenLastCalledWith(expect.objectContaining({ post_id: 'post' }), { seconds: 30, duration: 120 }, { keepalive: true })
    expect(newSave).not.toHaveBeenCalled()
    unmount()
  })
})
