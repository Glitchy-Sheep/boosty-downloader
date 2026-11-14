import { QueryClient, queryOptions, useQuery } from '@tanstack/react-query'

import { getAuthor, getAuthors, getPost, getPosts, getTags } from '@/lib/api'
import { toPostFilters, type Filters } from '@/lib/filters'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false },
    },
  })
}

export function authorsQuery() {
  return queryOptions({
    queryKey: ['authors'],
    queryFn: ({ signal }) => getAuthors(signal),
  })
}

export function authorQuery(author: string) {
  return queryOptions({
    queryKey: ['author', author],
    queryFn: ({ signal }) => getAuthor(author, signal),
  })
}

export function postsQuery(author: string, filters: Filters) {
  return queryOptions({
    queryKey: ['posts', author, toPostFilters(filters)],
    queryFn: ({ signal }) => getPosts(author, filters, signal),
  })
}

export function postQuery(author: string, postId: string) {
  return queryOptions({
    queryKey: ['post', author, postId],
    queryFn: ({ signal }) => getPost(author, postId, signal),
  })
}

export function tagsQuery(author: string) {
  return queryOptions({
    queryKey: ['tags', author],
    queryFn: ({ signal }) => getTags(author, signal),
  })
}

export function usePostList(author: string, filters: Filters) {
  return useQuery({
    ...postsQuery(author, filters),
    placeholderData: (previous, query) => query?.queryKey[1] === author ? previous : undefined,
  })
}
