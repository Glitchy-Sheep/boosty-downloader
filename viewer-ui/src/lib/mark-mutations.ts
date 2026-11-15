import { hashKey, MutationObserver, type QueryClient } from '@tanstack/react-query'

import { setFavorite, setSeen } from '@/lib/api'
import type { MarkResult } from '@/lib/api.gen'
import {
  acceptPostMark,
  applyPostMark,
  cachedPostMarkRequest,
  rollbackPostMark,
  type AppliedPostMark,
} from '@/lib/mark-cache'
import { markMutationKeys } from '@/lib/mark-keys'
import { settleActiveReads } from '@/lib/mutation-reads'
import type { PostMarkKind, PostMarkRequest } from '@/lib/post-marks'
import { authorQuery, authorsQuery, postQuery } from '@/lib/queries'

function writePostMark(request: PostMarkRequest): Promise<MarkResult> {
  const { author, postId, change } = request
  switch (change.kind) {
    case 'seen':
      return setSeen(author, postId, change.next.seen)
    case 'favorite':
      return setFavorite(author, postId, change.next)
  }
}

async function refreshMarkReads(client: QueryClient, request: PostMarkRequest): Promise<void> {
  const { author, postId } = request
  const refresh: Promise<void>[] = []
  if (client.isMutating({ mutationKey: markMutationKeys.post(author, postId) }) === 1) {
    refresh.push(client.invalidateQueries({ queryKey: postQuery(author, postId).queryKey }))
  }
  if (client.isMutating({ mutationKey: markMutationKeys.author(author) }) === 1) {
    refresh.push(client.invalidateQueries({ queryKey: ['posts', author] }))
    refresh.push(client.invalidateQueries({ queryKey: ['media', author] }))
    refresh.push(client.invalidateQueries({ queryKey: authorQuery(author).queryKey }))
  }
  if (client.isMutating({ mutationKey: markMutationKeys.all }) === 1) {
    refresh.push(client.invalidateQueries({ queryKey: authorsQuery().queryKey }))
  }
  await Promise.all(refresh)
}

function relatedReads(author: string, postId: string) {
  return [
    ['post', author, postId],
    ['posts', author],
    ['media', author],
    authorQuery(author).queryKey,
    authorsQuery().queryKey,
  ]
}

/** A physical-key action uses the post identity at the instant it is pressed. */
export function togglePostMark(
  client: QueryClient,
  author: string,
  postId: string,
  kind: PostMarkKind,
): void {
  const mutationKey = markMutationKeys.single(author, postId, kind)
  if (client.isMutating({ mutationKey, exact: true })) return
  if (client.isMutating({ mutationKey: markMutationKeys.bulk(author) })) return
  const request = cachedPostMarkRequest(client, author, postId, kind)
  if (!request) return
  const observer = new MutationObserver<MarkResult, Error, PostMarkRequest, AppliedPostMark>(
    client,
    {
      mutationKey,
      scope: { id: hashKey(markMutationKeys.author(author)) },
      mutationFn: writePostMark,
      onMutate: (variables) => applyPostMark(client, variables),
      onSuccess: async (result, variables, context) => {
        if (!context) return
        context.phase = 'refreshing'
        await settleActiveReads(client, relatedReads(author, postId))
        acceptPostMark(
          client,
          variables,
          result,
          context,
          client.isMutating({ mutationKey: markMutationKeys.author(author) }) === 1,
        )
      },
      onError: async (_error, variables, context) => {
        if (!context) return
        rollbackPostMark(client, variables, context)
        await settleActiveReads(client, relatedReads(author, postId))
      },
      onSettled: (_result, _error, variables) => refreshMarkReads(client, variables),
    },
  )
  const unsubscribe = observer.subscribe(() => {})
  void observer
    .mutate(request)
    .catch(() => {})
    .finally(unsubscribe)
}
