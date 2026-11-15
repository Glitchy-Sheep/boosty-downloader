import {
  createContext,
  createElement,
  useContext,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react'

import type { MediaItem, MediaPage, MediaPost } from '@/lib/api.gen'

export interface PlayerState {
  author: string
  queue: readonly MediaItem[]
  posts: Readonly<Record<string, MediaPost>>
  index: number
  request: number
  playing: boolean
}

type PlaybackFailureHandler = (request: number, error: unknown) => void

/** One application owns one queue; navigation does not replace its audio element. */
export function createPlayerStore() {
  let state: PlayerState | null = null
  let element: HTMLAudioElement | null = null
  let onFailure: PlaybackFailureHandler | undefined
  let revision = 0
  const listeners = new Set<() => void>()
  const publish = (next: PlayerState | null): void => {
    state = next
    for (const listener of listeners) listener()
  }
  return {
    getSnapshot: () => state,
    subscribe(this: void, listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    start(author: string, page: MediaPage, id: string): void {
      const queue = page.items.filter((item) => item.kind === 'audio')
      const index = queue.findIndex((item) => item.id === id)
      if (index < 0) return
      element?.pause()
      publish({ author, queue, posts: page.posts, index, request: ++revision, playing: false })
    },
    attach(audio: HTMLAudioElement | null, reportFailure?: PlaybackFailureHandler): void {
      element = audio
      onFailure = reportFailure
    },
    async toggle(): Promise<void> {
      if (!element) return
      if (element.paused) {
        const request = state?.request
        await element.play().catch((error: unknown) => {
          if (request !== undefined) onFailure?.(request, error)
        })
      } else element.pause()
    },
    setPlaying(playing: boolean): void {
      if (state && state.playing !== playing) publish({ ...state, playing })
    },
    step(delta: -1 | 1): void {
      if (!state) return
      const index = state.index + delta
      if (index < 0 || index >= state.queue.length) return
      element?.pause()
      publish({ ...state, index, request: ++revision, playing: false })
    },
    refresh(author: string, item: MediaItem): void {
      if (state?.author !== author || !state.queue.some((queued) => queued.id === item.id)) return
      publish({
        ...state,
        queue: state.queue.map((queued) => (queued.id === item.id ? item : queued)),
      })
    },
    close(): void {
      element?.pause()
      publish(null)
    },
  }
}

export type PlayerStore = ReturnType<typeof createPlayerStore>
const PlayerContext = createContext<PlayerStore | null>(null)

export function PlayerProvider({ children, store }: { children: ReactNode; store?: PlayerStore }) {
  const [ownedStore] = useState(createPlayerStore)
  return createElement(PlayerContext, { value: store ?? ownedStore }, children)
}

export function usePlayerStore(): PlayerStore {
  const store = useContext(PlayerContext)
  if (!store) throw new Error('Player components require PlayerProvider')
  return store
}

export function usePlayerState(): PlayerState | null {
  const store = usePlayerStore()
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
}

export function currentTrack(state: PlayerState | null): MediaItem | undefined {
  return state?.queue[state.index]
}
