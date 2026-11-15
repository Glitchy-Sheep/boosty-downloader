import { MutationObserver, type MutationKey, type QueryClient } from '@tanstack/react-query'

import { savePlaybackPosition } from '@/lib/api'
import type { MediaItem, PositionRequest } from '@/lib/api.gen'
import { settleActiveReads, type WriteContext } from '@/lib/mutation-reads'
import { acceptPosition } from '@/lib/playback-cache'
import { playbackMutationKeys } from '@/lib/playback-keys'

/** The playback controller owns write order and retries; reads track each saved change. */
export async function saveMediaPosition(
  client: QueryClient,
  author: string,
  postId: string,
  media: MediaItem,
  position: PositionRequest,
  keepalive: boolean,
): Promise<MediaItem> {
  const mutationKey = playbackMutationKeys.media(author, postId, media.id)
  const previousFinished = lastFinished(client, mutationKey, media)
  const observer = new MutationObserver<MediaItem, Error, PositionRequest, WriteContext>(client, {
    mutationKey,
    mutationFn: (request) => savePlaybackPosition(author, media.id, request, keepalive),
    onMutate: () => ({ phase: 'writing' }),
    onSuccess: async (saved, _request, context) => {
      if (context) context.phase = 'refreshing'
      await settleActiveReads(client, [
        ['post', author, postId],
        ['media', author],
      ])
      acceptPosition(client, author, postId, saved, previousFinished)
    },
    onError: async (_error, _request, context) => {
      if (context) context.phase = 'refreshing'
      await settleActiveReads(client, [
        ['post', author, postId],
        ['media', author],
      ])
      await Promise.all([
        client.invalidateQueries({ queryKey: ['post', author, postId] }),
        client.invalidateQueries({ queryKey: ['media', author] }),
      ])
    },
  })
  const unsubscribe = observer.subscribe(() => {})
  try {
    return await observer.mutate(position)
  } finally {
    unsubscribe()
  }
}

function lastFinished(
  client: QueryClient,
  mutationKey: MutationKey,
  media: MediaItem,
): boolean | undefined {
  const previous = client
    .getMutationCache()
    .findAll({ mutationKey, exact: true })
    .findLast((mutation) => mutation.state.status !== 'pending')
  if (!previous) return media.finished
  // A failed write can still have changed the durable position.
  if (previous.state.status === 'error') return undefined
  const saved = previous.state.data as MediaItem
  return saved.finished
}
