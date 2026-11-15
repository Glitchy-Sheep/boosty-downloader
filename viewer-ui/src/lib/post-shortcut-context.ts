import type { QueryClient } from '@tanstack/react-query'
import type { HistoryLocation } from '@tanstack/react-router'

import { parseFilters, type Filters } from '@/lib/filters'
import { postNeighbours, type PostNeighbours } from '@/lib/post-neighbours'
import { postQuery, postsQuery } from '@/lib/queries'
import { parseViewerSearch } from '@/lib/url-search'

type PostAddress = { author: string; postId: string | null; filters: Filters }
export type PostShortcutContext = PostAddress & { neighbours: PostNeighbours | null }
export type PostShortcutTarget = { author: string; postId: string; filters: Filters }
type ShortcutLocation = Pick<HistoryLocation, 'pathname' | 'search'>

function postAddress(location: ShortcutLocation): PostAddress | null {
  const match = /^\/a\/([^/]+)(?:\/p\/([^/]+))?\/?$/.exec(location.pathname)
  if (!match?.[1]) return null
  try {
    return {
      author: decodeURIComponent(match[1]),
      postId: match[2] ? decodeURIComponent(match[2]) : null,
      filters: parseFilters(parseViewerSearch(location.search)),
    }
  } catch {
    return null
  }
}

/** Resolve each press against the latest address and its exact filtered list. */
export function readPostShortcutContext(
  client: QueryClient,
  location: ShortcutLocation,
  activeAuthor: string,
): PostShortcutContext | null {
  const address = postAddress(location)
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
