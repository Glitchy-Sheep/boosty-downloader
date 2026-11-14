import { QueryClient, queryOptions, useQuery } from '@tanstack/react-query'

import { getAuthor, getAuthors, getPost, getPosts, getTags } from '@/lib/api'
import { toPostFilters, type Filters } from '@/lib/filters'
import { projectAuthorMarks, projectPostList, projectPostMarks } from '@/lib/mark-projection'
import { markMutationKeys } from '@/lib/mark-keys'
import { readAfterMarkWrites } from '@/lib/mark-reads'

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
    queryFn: async ({ signal, client }) =>
      (
        await readAfterMarkWrites(client, [markMutationKeys.all], signal, () => getAuthors(signal))
      ).map((author) => projectAuthorMarks(client, author)),
  })
}

export function authorQuery(author: string) {
  return queryOptions({
    queryKey: ['author', author],
    queryFn: async ({ signal, client }) =>
      projectAuthorMarks(
        client,
        await readAfterMarkWrites(client, [markMutationKeys.author(author)], signal, () =>
          getAuthor(author, signal),
        ),
      ),
  })
}

export function postsQuery(author: string, filters: Filters) {
  return queryOptions({
    queryKey: ['posts', author, toPostFilters(filters)],
    queryFn: async ({ signal, client }) =>
      projectPostList(
        client,
        author,
        toPostFilters(filters),
        await readAfterMarkWrites(client, [markMutationKeys.author(author)], signal, () =>
          getPosts(author, filters, signal),
        ),
      ),
  })
}

export function postQuery(author: string, postId: string) {
  return queryOptions({
    queryKey: ['post', author, postId],
    queryFn: async ({ signal, client }) =>
      projectPostMarks(
        client,
        author,
        await readAfterMarkWrites(
          client,
          [markMutationKeys.post(author, postId), markMutationKeys.bulk(author)],
          signal,
          () => getPost(author, postId, signal),
        ),
      ),
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
    placeholderData: (previous, query) => (query?.queryKey[1] === author ? previous : undefined),
  })
}
