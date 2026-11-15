import type { AuthorTab } from '@/lib/author-tab'
import type { Filters } from '@/lib/filters'
import type { MediaSearch } from '@/lib/media-filters'
import type { PostAddress } from '@/lib/post-address'

export type PostsPlace = {
  postId: string | undefined
  filters: Filters
  shows: 'post' | 'empty' | 'error' | 'loading'
  error: unknown
}

export type MediaPlace = { filters: MediaSearch; error: unknown }
export type ShownPlace = { tab: 'posts'; place: PostsPlace } | { tab: 'media'; place: MediaPlace }

export type AuthorPlaces = {
  shown: AuthorTab | null
  posts: PostsPlace | undefined
  media: MediaPlace | undefined
}

/** A newly selected post must not display the previous post's content or controls. */
export function pendingPostPlace(
  previous: AuthorPlaces,
  incoming: ShownPlace | null,
  address: PostAddress | null,
): ShownPlace | null {
  if (previous.shown !== 'posts' || !address?.postId) return incoming
  if (incoming?.tab === 'posts' && incoming.place.postId === address.postId) return incoming
  if (previous.posts?.postId === address.postId && previous.posts.shows !== 'loading')
    return incoming
  return {
    tab: 'posts',
    place: { postId: address.postId, filters: address.filters, shows: 'loading', error: undefined },
  }
}

function samePlace(previous: PostsPlace | MediaPlace | undefined, next: PostsPlace | MediaPlace) {
  if (!previous || previous.error !== next.error) return false
  if (JSON.stringify(previous.filters) !== JSON.stringify(next.filters)) return false
  if ('shows' in next)
    return 'shows' in previous && previous.shows === next.shows && previous.postId === next.postId
  return !('shows' in previous)
}

/** Keep the outgoing content, including errors, until the next route is ready. */
export function retainAuthorPlace(
  previous: AuthorPlaces,
  incoming: ShownPlace | null,
): AuthorPlaces {
  if (!incoming) return previous
  if (previous.shown === incoming.tab && samePlace(previous[incoming.tab], incoming.place))
    return previous
  switch (incoming.tab) {
    case 'posts':
      return { ...previous, shown: 'posts', posts: incoming.place }
    case 'media':
      return { ...previous, shown: 'media', media: incoming.place }
  }
}
