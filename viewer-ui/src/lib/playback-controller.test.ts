import { fireEvent, screen } from '@testing-library/dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { attachPostPlayback } from '@/lib/playback-controller'
import { deferred, nativePlayer, playbackItem, setPlaying } from '@/test/playback-fixture'

describe('native post playback', () => {
  let cleanup: (() => void) | undefined
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
  })
  afterEach(() => {
    cleanup?.()
    cleanup = undefined
    document.body.replaceChildren()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('waits for metadata, resumes once, and saves Start over without playing', async () => {
    const video = nativePlayer(document.body)
    Object.defineProperty(video, 'readyState', { value: 0, writable: true })
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    expect(video.currentTime).toBe(0)
    fireEvent.loadedMetadata(video)
    expect(video.currentTime).toBe(12)
    expect(screen.getByText('Resumed at 0:12')).toHaveAttribute('data-page-generated', 'true')
    video.currentTime = 20
    fireEvent.loadedMetadata(video)
    expect(video.currentTime).toBe(20)
    fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
    expect(video.currentTime).toBe(0)
    expect(save).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ id: 'opaque-media' }),
      { seconds: 0, duration: 120 },
      { keepalive: true },
    )
    await Promise.resolve()
    expect(screen.queryByRole('button', { name: 'Start over' })).not.toBeInTheDocument()
  })

  it('saves changed positions and does not repeat a paused position on hide, pagehide or cleanup', () => {
    const audio = nativePlayer(document.body, 'audio')
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(audio, playbackItem({ kind: 'audio' }), save)
    setPlaying(audio)
    audio.currentTime = 22
    vi.advanceTimersByTime(4_999)
    expect(save).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(save).toHaveBeenLastCalledWith(
      expect.anything(),
      { seconds: 22, duration: 120 },
      { keepalive: true },
    )
    Object.defineProperty(audio, 'paused', { value: true, writable: true })
    audio.currentTime = 25
    fireEvent.pause(audio)
    vi.advanceTimersByTime(10_000)
    expect(save).toHaveBeenCalledTimes(2)
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    fireEvent(document, new Event('visibilitychange'))
    fireEvent(window, new Event('pagehide'))
    cleanup()
    cleanup = undefined
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith(
      expect.anything(),
      { seconds: 25, duration: 120 },
      { keepalive: true },
    )
    fireEvent.pause(audio)
    fireEvent(window, new Event('pagehide'))
    expect(save).toHaveBeenCalledTimes(2)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not overwrite saved or finished marks by merely displaying a player', () => {
    const video = nativePlayer(document.body)
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem({ finished: true }), save)
    fireEvent.pause(video)
    fireEvent(window, new Event('pagehide'))
    cleanup()
    cleanup = undefined
    expect(video.currentTime).toBe(0)
    expect(save).not.toHaveBeenCalled()
  })

  it('persists paused seeking and the exact ending without nonfinite values', () => {
    const video = nativePlayer(document.body)
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    fireEvent.seeked(video)
    expect(save).not.toHaveBeenCalled()
    video.currentTime = 44
    fireEvent.seeked(video)
    expect(save).toHaveBeenLastCalledWith(
      expect.anything(),
      { seconds: 44, duration: 120 },
      { keepalive: true },
    )
    video.currentTime = 120
    fireEvent.ended(video)
    expect(save).toHaveBeenLastCalledWith(
      expect.anything(),
      { seconds: 120, duration: 120 },
      { keepalive: true },
    )
    Object.defineProperty(video, 'duration', { value: NaN, writable: true })
    fireEvent.pause(video)
    expect(save).toHaveBeenCalledTimes(2)
  })

  it('saves a later manual seek back to the initial resume point', () => {
    const video = nativePlayer(document.body)
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    fireEvent.seeked(video)
    video.currentTime = 44
    fireEvent.seeked(video)
    video.currentTime = 12
    fireEvent.seeked(video)
    expect(save).toHaveBeenLastCalledWith(
      expect.anything(),
      { seconds: 12, duration: 120 },
      { keepalive: true },
    )
    expect(save).toHaveBeenCalledTimes(2)
  })

  it('resumes when Play was requested before metadata arrived', () => {
    const video = nativePlayer(document.body)
    Object.defineProperty(video, 'readyState', { value: 0, writable: true })
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    setPlaying(video)
    fireEvent.loadedMetadata(video)
    expect(video.currentTime).toBe(12)
  })

  it('keeps playback already advanced before metadata and ignores early seeks and visible-page events', () => {
    const video = nativePlayer(document.body)
    Object.defineProperty(video, 'readyState', { value: 0, writable: true })
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    video.currentTime = 3
    fireEvent.seeked(video)
    expect(save).not.toHaveBeenCalled()
    setPlaying(video)
    video.currentTime = 8
    fireEvent.loadedMetadata(video)
    expect(video.currentTime).toBe(8)
    expect(screen.queryByText(/Resumed at/)).not.toBeInTheDocument()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    fireEvent(document, new Event('visibilitychange'))
    expect(save).not.toHaveBeenCalled()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    fireEvent(document, new Event('visibilitychange'))
    expect(save).toHaveBeenCalledExactlyOnceWith(
      expect.anything(),
      { seconds: 8, duration: 120 },
      { keepalive: true },
    )
  })

  it('does not periodically save a native player that stopped before its stop event arrives', () => {
    const video = nativePlayer(document.body)
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    setPlaying(video)
    Object.defineProperty(video, 'paused', { value: true, writable: true })
    vi.advanceTimersByTime(5_000)
    expect(save).not.toHaveBeenCalled()
    Object.defineProperty(video, 'paused', { value: false, writable: true })
    Object.defineProperty(video, 'ended', { value: true, writable: true })
    vi.advanceTimersByTime(5_000)
    expect(save).not.toHaveBeenCalled()
  })

  it('shows save failure, keeps playback alive, and clears it after a successful retry', async () => {
    const video = nativePlayer(document.body)
    const save = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    setPlaying(video)
    video.currentTime = 20
    await vi.advanceTimersByTimeAsync(5_000)
    expect(screen.getByRole('status')).toHaveTextContent('Playback position could not be saved.')
    expect(video.paused).toBe(false)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('does not show an old failure after a newer save or add notes after cleanup', async () => {
    const video = nativePlayer(document.body)
    const pending = deferred()
    const save = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    setPlaying(video)
    await vi.advanceTimersByTimeAsync(5_000)
    video.currentTime = 25
    await vi.advanceTimersByTimeAsync(5_000)
    pending.reject(new Error('late failure'))
    await vi.advanceTimersByTimeAsync(0)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    cleanup()
    cleanup = undefined
    await vi.advanceTimersByTimeAsync(0)
    expect(document.querySelector('[data-page-generated]')).toBeNull()
  })

  it('removes listeners and resume controls before rebinding the same element', () => {
    const video = nativePlayer(document.body)
    const save = vi.fn().mockResolvedValue(undefined)
    cleanup = attachPostPlayback(video, playbackItem(), save)
    cleanup()
    cleanup = attachPostPlayback(video, playbackItem(), save)
    expect(screen.getAllByRole('button', { name: 'Start over' })).toHaveLength(1)
    setPlaying(video)
    vi.advanceTimersByTime(5_000)
    expect(save).toHaveBeenCalledOnce()
  })
})
