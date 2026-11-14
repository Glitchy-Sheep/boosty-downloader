import { useLayoutEffect, useRef, type RefObject } from 'react'
import type { MediaItem } from '@/lib/api.gen'
import { attachPostPlayback } from '@/lib/playback-controller'
import { findPlaybackMedia, playerSource } from '@/lib/playback-media'
import { pendingPlaybackMark } from '@/lib/playback-position'
import { pendingPlaybackPosition, writePlaybackPosition, type SavePosition } from '@/lib/playback-writes'

export type { SavePosition } from '@/lib/playback-writes'

interface PostPlaybackOptions {
  rootRef: RefObject<HTMLDivElement | null>
  author: string
  postId: string
  html: string
  media: readonly MediaItem[]
  savePosition: SavePosition
}

export function usePostPlayback(options: PostPlaybackOptions): void {
  const latest = useRef(options)
  const { rootRef, author, postId, html, media } = options
  const inventory = JSON.stringify(media.map(({ id, path, kind }) => ({ id, path, kind })))
  useLayoutEffect(() => {
    latest.current = options
  }, [options])

  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return
    const initial = latest.current
    const origin = window.location.origin
    const cleanups: Array<() => void> = []
    for (const element of root.querySelectorAll<HTMLMediaElement>('video, audio')) {
      const item = findPlaybackMedia(playerSource(element), author, postId, initial.media, origin)
      if (!item) continue
      const identity = { origin, author, postId, mediaId: item.id }
      const pending = pendingPlaybackPosition(identity)
      const resumedItem = pending ? { ...item, ...pendingPlaybackMark(pending.position) } : item
      const save: SavePosition = (savedItem, position) => {
        const current = latest.current
        const owner = current.author === author && current.postId === postId ? current : initial
        return writePlaybackPosition(identity, savedItem, position, owner.savePosition)
      }
      cleanups.push(attachPostPlayback(element, resumedItem, save, pending?.completion))
    }
    return () => cleanups.forEach((cleanup) => cleanup())
  }, [rootRef, author, postId, html, inventory])
}
