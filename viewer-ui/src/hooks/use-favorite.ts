import { useMutation, useMutationState, useQueryClient } from '@tanstack/react-query'

import { setFavorite } from '@/lib/api'
import { acceptFavorite, applyFavorite, rollbackFavorite } from '@/lib/favorite-cache'
import { authorQuery, authorsQuery, postQuery } from '@/lib/queries'

type FavoriteRequest = { previous: boolean; favorite: boolean }
const FAVORITE_MUTATION = 'favorite'

/** Share the page heart with other views without replacing the retained post detail. */
export function useFavorite(author: string, postId: string) {
  const client = useQueryClient()
  const mutationKey = [FAVORITE_MUTATION, author, postId]
  const states = useMutationState({
    filters: { mutationKey, exact: true },
    select: (value) => ({ status: value.state.status, error: value.state.error?.message ?? null }),
  })
  const pending = states.some((state) => state.status === 'pending')
  const mutation = useMutation({
    mutationKey,
    // Author totals must not overtake another pending favorite response.
    scope: { id: FAVORITE_MUTATION },
    mutationFn: ({ favorite }: FavoriteRequest) => setFavorite(author, postId, favorite),
    onMutate: async (request: FavoriteRequest) => {
      await Promise.all([
        client.cancelQueries({ queryKey: postQuery(author, postId).queryKey }),
        client.cancelQueries({ queryKey: ['posts', author] }),
        client.cancelQueries({ queryKey: authorQuery(author).queryKey }),
        client.cancelQueries({ queryKey: authorsQuery().queryKey }),
      ])
      return applyFavorite(client, { author, postId, ...request })
    },
    onSuccess: (result) =>
      acceptFavorite(
        client,
        author,
        result,
        client.isMutating({ mutationKey: [FAVORITE_MUTATION, author] }) === 1,
      ),
    onError: (_error, _request, change) => {
      if (change) rollbackFavorite(client, change)
    },
    onSettled: async () => {
      const refresh = [client.invalidateQueries({ queryKey: postQuery(author, postId).queryKey })]
      if (client.isMutating({ mutationKey: [FAVORITE_MUTATION, author] }) === 1) {
        refresh.push(client.invalidateQueries({ queryKey: ['posts', author] }))
        refresh.push(client.invalidateQueries({ queryKey: authorQuery(author).queryKey }))
      }
      if (client.isMutating({ mutationKey: [FAVORITE_MUTATION] }) === 1) {
        refresh.push(client.invalidateQueries({ queryKey: authorsQuery().queryKey }))
      }
      await Promise.all(refresh)
    },
  })
  const toggle = (): void => {
    if (client.isMutating({ mutationKey })) return
    const post = client.getQueryData(postQuery(author, postId).queryKey)
    if (!post || post.access === 'locked') return
    mutation.mutate({ previous: post.favorite, favorite: !post.favorite })
  }
  return { toggle, pending, error: states.at(-1)?.error ?? null }
}
