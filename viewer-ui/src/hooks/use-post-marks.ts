import { useIsMutating, useMutationState, useQueryClient } from '@tanstack/react-query'

import { markMutationKeys } from '@/lib/mark-keys'
import { togglePostMark } from '@/lib/mark-mutations'
import type { PostMarkKind } from '@/lib/post-marks'

function useMarkState(author: string, postId: string, kind: PostMarkKind) {
  const states = useMutationState({
    filters: { mutationKey: markMutationKeys.single(author, postId, kind), exact: true },
    select: (mutation) => ({
      status: mutation.state.status,
      error: mutation.state.error?.message ?? null,
    }),
  })
  return {
    pending: states.some((state) => state.status === 'pending'),
    error: states.at(-1)?.error ?? null,
  }
}

export function usePostMarkActions(author: string) {
  const client = useQueryClient()
  return {
    toggleSeen: (postId: string): void => togglePostMark(client, author, postId, 'seen'),
    toggleFavorite: (postId: string): void => togglePostMark(client, author, postId, 'favorite'),
  }
}

/** Row, page and keyboard controls share pending work and retained error feedback. */
export function usePostMarks(author: string, postId: string) {
  const seen = useMarkState(author, postId, 'seen')
  const favorite = useMarkState(author, postId, 'favorite')
  const bulkPending = useIsMutating({ mutationKey: markMutationKeys.bulk(author) }) > 0
  const actions = usePostMarkActions(author)
  return {
    seen: {
      ...seen,
      pending: seen.pending || bulkPending,
      toggle: () => actions.toggleSeen(postId),
    },
    favorite: {
      ...favorite,
      pending: favorite.pending || bulkPending,
      toggle: () => actions.toggleFavorite(postId),
    },
  }
}
