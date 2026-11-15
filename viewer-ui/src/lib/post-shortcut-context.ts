import type { QueryClient } from '@tanstack/react-query'
import type { Filters } from '@/lib/filters'
import { readPostAddress, type PostAddress, type PostLocation } from '@/lib/post-address'
import { postNeighbours, type PostNeighbours } from '@/lib/post-neighbours'
import { postQuery, postsQuery } from '@/lib/queries'
export type PostShortcutContext = PostAddress & { neighbours: PostNeighbours | null }
export type PostShortcutTarget = { author: string; postId: string; filters: Filters }

/** Resolve each press against the latest address and its exact filtered list. */
export function readPostShortcutContext(
  client: QueryClient,
  location: PostLocation,
  activeAuthor: string,
): PostShortcutContext | null {
  const address = readPostAddress(location)
  if (!address || address.author !== activeAuthor) return null
  const context: PostShortcutContext = { ...address, neighbours: null }
  if (!address.postId) return context
  const list = client.getQueryState(postsQuery(address.author, address.filters).queryKey)
  if (list?.status !== 'success' || !list.data) return context
  const current =
    list.data.rows.find((post) => post.id === address.postId) ??
    client.getQueryData(postQuery(address.author, address.postId).queryKey)
  if (current) context.neighbours = postNeighbours(list.data.rows, current, address.filters.order)
  return context
}
