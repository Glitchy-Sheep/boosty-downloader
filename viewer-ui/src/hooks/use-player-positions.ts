import { matchMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import type { MediaItem } from '@/lib/api.gen'
import { playbackMutationKeys } from '@/lib/playback-keys'
import { usePlayerStore } from '@/lib/player'

/** Post and fullscreen players share their canonical saved positions with the audio queue. */
export function usePlayerPositions(): void {
  const client = useQueryClient()
  const store = usePlayerStore()
  useEffect(
    () =>
      client.getMutationCache().subscribe((event) => {
        if (event.type !== 'updated' || event.action.type !== 'success') return
        if (!matchMutation({ mutationKey: playbackMutationKeys.all }, event.mutation)) return
        const author = event.mutation.options.mutationKey?.[1]
        if (typeof author !== 'string') return
        const saved = event.mutation.state.data as MediaItem
        store.refresh(author, saved)
      }),
    [client, store],
  )
}
