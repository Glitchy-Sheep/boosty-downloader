import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'

import { mediaPath } from '@/lib/media-paths'
import { attachPostPlayback } from '@/lib/playback-controller'
import { saveMediaPosition } from '@/lib/playback-mutations'
import { pendingPlaybackMark } from '@/lib/playback-position'
import {
  createPlaybackActivity,
  pendingPlaybackPosition,
  writePlaybackPosition,
  type SavePosition,
} from '@/lib/playback-writes'
import { currentTrack, type PlayerState, type PlayerStore } from '@/lib/player'

type PlayerPlaybackOptions = {
  audio: RefObject<HTMLAudioElement | null>
  state: PlayerState | null
  store: PlayerStore
  rate: number
  onFailure: (request: number, error: unknown) => void
}

/** Detach and save the previous track before changing the persistent element's source. */
export function usePlayerPlayback(options: PlayerPlaybackOptions): void {
  const client = useQueryClient()
  const latest = useRef(options)
  const request = options.state?.request
  useLayoutEffect(() => {
    latest.current = options
  }, [options])
  useLayoutEffect(() => {
    const { audio, state, store, rate } = latest.current
    const element = audio.current
    const item = currentTrack(state)
    if (!element || !state || !item) return
    const { author } = state
    const identity = {
      origin: window.location.origin,
      author,
      postId: item.post_id,
      mediaId: item.id,
    }
    const pending = pendingPlaybackPosition(identity)
    const resumed = pending ? { ...item, ...pendingPlaybackMark(pending.position) } : item
    const save: SavePosition = async (saved, position, settings) => {
      const queue = store.getSnapshot()
      const current =
        queue?.author === author ? queue.queue.find((queued) => queued.id === saved.id) : undefined
      await saveMediaPosition(
        client,
        author,
        saved.post_id,
        current ?? saved,
        position,
        settings.keepalive,
      )
    }
    element.src = mediaPath(author, item.path)
    element.load()
    element.playbackRate = rate
    return attachPostPlayback(
      element,
      resumed,
      (saved, position) => writePlaybackPosition(identity, saved, position, save),
      pending?.completion,
      createPlaybackActivity(identity),
    )
  }, [client, request])
  useEffect(() => {
    const { audio, state, onFailure } = latest.current
    if (!state || !audio.current) return
    void audio.current.play().catch((error: unknown) => onFailure(state.request, error))
  }, [request])
}
