import type { HistoryLocation } from '@tanstack/react-router'

import { parseFilters, type Filters } from '@/lib/filters'
import { parseViewerSearch } from '@/lib/url-search'

export type PostAddress = { author: string; postId: string | null; filters: Filters }
export type PostLocation = Pick<HistoryLocation, 'pathname' | 'search'>

export function readPostAddress(location: PostLocation): PostAddress | null {
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
