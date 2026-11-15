import { act, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { MediaPage } from '@/lib/api.gen'
import {
  createPlayerStore,
  currentTrack,
  PlayerProvider,
  usePlayerState,
  usePlayerStore,
} from '@/lib/player'
import { playbackItem } from '@/test/playback-fixture'

const first = playbackItem({ id: 'first', kind: 'audio' })
const last = playbackItem({ id: 'last', kind: 'audio', removed: true })
const page: MediaPage = {
  items: [first, playbackItem({ id: 'video' }), last],
  posts: {
    post: { access: 'open', title: 'Post', cover_path: null, seen: false, favorite: false },
  },
  missing: 0,
  counts: { all: 3, audio: 2, videos: 1, files: 0, images: 0 },
}

test('queue follows filtered audio order including removed pieces and does not wrap', () => {
  const store = createPlayerStore()
  const change = vi.fn()
  const unsubscribe = store.subscribe(change)
  store.start('author', page, 'video')
  expect(store.getSnapshot()).toBeNull()
  store.step(1)
  store.refresh('author', first)
  store.setPlaying(true)
  store.start('author', page, first.id)
  expect(store.getSnapshot()?.queue).toEqual([first, last])
  const initial = store.getSnapshot()?.request
  store.step(-1)
  expect(store.getSnapshot()?.request).toBe(initial)
  store.step(1)
  expect(currentTrack(store.getSnapshot())).toBe(last)
  store.step(1)
  expect(currentTrack(store.getSnapshot())).toBe(last)
  store.step(-1)
  expect(currentTrack(store.getSnapshot())).toBe(first)
  unsubscribe()
  const calls = change.mock.calls.length
  store.close()
  expect(change).toHaveBeenCalledTimes(calls)
})

test('canonical refresh is scoped to author and preserves the active request', () => {
  const store = createPlayerStore()
  store.start('author', page, first.id)
  const request = store.getSnapshot()?.request
  store.setPlaying(true)
  const playing = store.getSnapshot()
  store.setPlaying(true)
  expect(store.getSnapshot()).toBe(playing)
  store.refresh('other', { ...first, position_s: 70 })
  store.refresh('author', playbackItem({ id: 'absent' }))
  expect(store.getSnapshot()).toBe(playing)
  const canonical = { ...first, position_s: 48, duration_s: 99 }
  store.refresh('author', canonical)
  expect(currentTrack(store.getSnapshot())).toBe(canonical)
  expect(store.getSnapshot()).toMatchObject({ request, playing: true })
  store.close()
  store.start('author', page, first.id)
  expect(store.getSnapshot()?.request).toBeGreaterThan(request ?? 0)
})

test('play controls use the attached element and report rejected play requests', async () => {
  const store = createPlayerStore()
  await store.toggle()
  const audio = document.createElement('audio')
  const play = vi.spyOn(audio, 'play').mockResolvedValue()
  const pause = vi.spyOn(audio, 'pause').mockImplementation(() => {})
  const failure = vi.fn()
  store.attach(audio, failure)
  store.start('author', page, first.id)
  await store.toggle()
  expect(play).toHaveBeenCalledOnce()
  const error = new Error('Broken media')
  play.mockRejectedValue(error)
  await store.toggle()
  expect(failure).toHaveBeenCalledWith(store.getSnapshot()?.request, error)
  Object.defineProperty(audio, 'paused', { value: false })
  await store.toggle()
  store.close()
  expect(pause).toHaveBeenCalledTimes(3)
  store.attach(null)
})

function Consumer() {
  const store = usePlayerStore()
  const state = usePlayerState()
  return (
    <button type="button" onClick={() => store.start('author', page, first.id)}>
      {currentTrack(state)?.id ?? 'empty'}
    </button>
  )
}

test('providers isolate queues and support an injected observable store', () => {
  const store = createPlayerStore()
  render(
    <>
      <PlayerProvider store={store}>
        <Consumer />
      </PlayerProvider>
      <PlayerProvider>
        <Consumer />
      </PlayerProvider>
    </>,
  )
  act(() => store.start('author', page, last.id))
  expect(screen.getByRole('button', { name: 'last' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'empty' })).toBeInTheDocument()
})

test('player consumers require their application provider', () => {
  const log = vi.spyOn(console, 'error').mockImplementation(() => {})
  expect(() => render(<Consumer />)).toThrow('Player components require PlayerProvider')
  log.mockRestore()
})
