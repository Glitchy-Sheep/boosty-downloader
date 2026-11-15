import { fireEvent } from '@testing-library/dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { attachPostPlayback } from '@/lib/playback-controller'
import {
  createPlaybackWriter,
  type PlaybackIdentity,
  type SavePosition,
} from '@/lib/playback-writes'
import { deferred, nativePlayer, playbackItem, setPlaying } from '@/test/playback-fixture'

const identity: PlaybackIdentity = {
  origin: 'http://localhost',
  author: 'author',
  postId: 'post',
  mediaId: 'audio',
}
const cleanups: Array<() => void> = []

beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    Object.defineProperty(this, 'paused', { configurable: true, value: true })
    fireEvent.pause(this)
  })
})
afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  document.body.replaceChildren()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function bind(
  writer: ReturnType<typeof createPlaybackWriter>,
  save: SavePosition,
  owner = identity,
) {
  const element = nativePlayer(document.body, 'audio')
  const item = playbackItem({ id: owner.mediaId, kind: 'audio' })
  const cleanup = attachPostPlayback(
    element,
    item,
    (media, position) => writer.write(owner, media, position, save),
    undefined,
    writer.activity(owner),
  )
  cleanups.push(cleanup)
  return element
}

test('a failed pause can retry while another different track plays', async () => {
  const writer = createPlaybackWriter()
  const save = vi
    .fn<SavePosition>()
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue(undefined)
  const first = bind(writer, save)
  setPlaying(first)
  first.currentTime = 35
  first.pause()
  await vi.advanceTimersByTimeAsync(0)
  const second = bind(writer, vi.fn<SavePosition>().mockResolvedValue(undefined), {
    ...identity,
    mediaId: 'other',
  })
  setPlaying(second)
  fireEvent(window, new Event('pagehide'))
  await vi.advanceTimersByTimeAsync(0)
  expect(save).toHaveBeenCalledTimes(2)
  expect(save).toHaveBeenLastCalledWith(
    expect.anything(),
    { seconds: 35, duration: 120 },
    { keepalive: true },
  )
})

test('manual seek reclaims an old player after a same-track failure was superseded', async () => {
  const writer = createPlaybackWriter()
  const save = vi
    .fn<SavePosition>()
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue(undefined)
  const first = bind(writer, save)
  setPlaying(first)
  first.currentTime = 35
  first.pause()
  await vi.advanceTimersByTimeAsync(0)
  const second = bind(writer, vi.fn<SavePosition>().mockResolvedValue(undefined))
  setPlaying(second)
  second.currentTime = 75
  second.pause()
  await vi.advanceTimersByTimeAsync(0)
  fireEvent(window, new Event('pagehide'))
  await vi.advanceTimersByTimeAsync(0)
  expect(save).toHaveBeenCalledOnce()
  first.currentTime = 10
  fireEvent.seeked(first)
  await vi.advanceTimersByTimeAsync(0)
  expect(save).toHaveBeenCalledTimes(2)
  expect(save).toHaveBeenLastCalledWith(
    expect.anything(),
    { seconds: 10, duration: 120 },
    { keepalive: true },
  )
})

test('an older pending write stays before the new owner and cleanup cannot append a stale retry', async () => {
  const writer = createPlaybackWriter()
  const pending = deferred()
  const oldSave = vi.fn<SavePosition>().mockReturnValue(pending.promise)
  const newSave = vi.fn<SavePosition>().mockResolvedValue(undefined)
  const first = bind(writer, oldSave)
  setPlaying(first)
  first.currentTime = 35
  first.pause()
  await vi.advanceTimersByTimeAsync(0)
  const second = bind(writer, newSave)
  setPlaying(second)
  second.currentTime = 75
  second.pause()
  cleanups.shift()?.()
  expect(newSave).not.toHaveBeenCalled()
  pending.resolve()
  await vi.advanceTimersByTimeAsync(0)
  expect(oldSave).toHaveBeenCalledOnce()
  expect(newSave).toHaveBeenCalledExactlyOnceWith(
    expect.anything(),
    { seconds: 75, duration: 120 },
    { keepalive: true },
  )
  expect(writer.pending(identity)).toBeUndefined()
})

test('releasing a superseded controller cannot revoke the current one, and released owners leave no activity', () => {
  const writer = createPlaybackWriter()
  const first = writer.activity(identity)
  const second = writer.activity(identity)
  expect(first.owns()).toBe(false)
  first.claim()
  second.claim()
  first.release()
  expect(second.owns()).toBe(true)
  second.release()
  expect(first.owns()).toBe(false)
  expect(second.owns()).toBe(false)
  expect(writer.activity(identity).owns()).toBe(false)
})

test('further playing progress is newer activity than a seek on another paused copy', async () => {
  const writer = createPlaybackWriter()
  const save = vi.fn<SavePosition>().mockResolvedValue(undefined)
  const playing = bind(writer, save)
  setPlaying(playing)
  playing.currentTime = 35
  await vi.advanceTimersByTimeAsync(5000)
  const paused = bind(writer, vi.fn<SavePosition>().mockResolvedValue(undefined))
  paused.currentTime = 10
  fireEvent.seeked(paused)
  await vi.advanceTimersByTimeAsync(0)
  playing.currentTime = 45
  await vi.advanceTimersByTimeAsync(5000)
  expect(save).toHaveBeenLastCalledWith(
    expect.anything(),
    { seconds: 45, duration: 120 },
    { keepalive: true },
  )
  expect(save).toHaveBeenCalledTimes(2)
})

test('late metadata cannot give an abandoned player new playback activity', async () => {
  const writer = createPlaybackWriter()
  const save = vi.fn<SavePosition>().mockResolvedValue(undefined)
  const old = nativePlayer(document.body, 'audio')
  Object.defineProperties(old, {
    readyState: { configurable: true, value: 0 },
    duration: { configurable: true, value: Number.NaN },
  })
  const cleanup = attachPostPlayback(
    old,
    playbackItem(),
    save,
    undefined,
    writer.activity(identity),
  )
  setPlaying(old)
  old.pause()
  const current = bind(writer, vi.fn<SavePosition>().mockResolvedValue(undefined))
  setPlaying(current)
  Object.defineProperty(old, 'duration', { configurable: true, value: 120 })
  fireEvent.loadedMetadata(old)
  cleanup()
  await vi.advanceTimersByTimeAsync(0)
  expect(save).not.toHaveBeenCalled()
})

test('late metadata cannot reclaim a completed seek from a newer player', async () => {
  const writer = createPlaybackWriter()
  const oldSave = vi.fn<SavePosition>().mockResolvedValue(undefined)
  const currentSave = vi.fn<SavePosition>().mockResolvedValue(undefined)
  const old = nativePlayer(document.body, 'audio')
  Object.defineProperties(old, {
    readyState: { configurable: true, value: 0 },
    duration: { configurable: true, value: Number.NaN },
  })
  const cleanup = attachPostPlayback(
    old,
    playbackItem(),
    oldSave,
    undefined,
    writer.activity(identity),
  )
  cleanups.push(cleanup)
  old.currentTime = 3
  fireEvent.seeking(old)
  fireEvent.seeked(old)
  expect(oldSave).not.toHaveBeenCalled()
  const current = bind(writer, currentSave)
  setPlaying(current)
  current.currentTime = 75
  current.pause()
  await vi.advanceTimersByTimeAsync(0)
  Object.defineProperty(old, 'duration', { configurable: true, value: 120 })
  fireEvent.loadedMetadata(old)
  cleanups.shift()?.()
  await vi.advanceTimersByTimeAsync(0)
  expect(old.currentTime).toBe(3)
  expect(oldSave).not.toHaveBeenCalled()
  expect(currentSave).toHaveBeenCalledExactlyOnceWith(
    expect.anything(),
    { seconds: 75, duration: 120 },
    { keepalive: true },
  )
})

test.each([
  { previousWrite: 'successful', fail: false, flush: 'pagehide' },
  { previousWrite: 'failed', fail: true, flush: 'cleanup' },
])(
  'duration refinement cannot reclaim a superseded $previousWrite pause on $flush',
  async ({ fail, flush }) => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
      this: HTMLMediaElement,
    ) {
      Object.defineProperty(this, 'paused', { configurable: true, value: true })
      setTimeout(() => fireEvent.pause(this), 0)
    })
    const writer = createPlaybackWriter()
    const save = vi.fn<SavePosition>().mockResolvedValue(undefined)
    if (fail) save.mockRejectedValueOnce(new Error('offline'))
    const old = bind(writer, save)
    setPlaying(old)
    old.currentTime = 35
    old.pause()
    await vi.advanceTimersByTimeAsync(0)
    const current = bind(writer, save)
    setPlaying(current)
    current.currentTime = 75
    current.pause()
    await vi.advanceTimersByTimeAsync(0)
    expect(save.mock.calls.map((call) => call[1].seconds)).toEqual([35, 75])

    Object.defineProperty(old, 'duration', { configurable: true, value: 121 })
    fireEvent.durationChange(old)
    if (flush === 'pagehide') fireEvent(window, new Event('pagehide'))
    else cleanups.shift()?.()
    await vi.advanceTimersByTimeAsync(0)

    expect(save.mock.calls.map((call) => call[1].seconds)).toEqual([35, 75])
  },
)
