import { QueryClient, queryOptions, useQuery } from '@tanstack/react-query'

import { getAuthor, getAuthors, getMedia, getPost, getPosts, getTags } from '@/lib/api'
import { toPostFilters, type Filters } from '@/lib/filters'
import { projectAuthorMarks, projectPostList, projectPostMarks } from '@/lib/mark-projection'
import { markMutationKeys } from '@/lib/mark-keys'
import { readAfterWrites } from '@/lib/mutation-reads'
import { toMediaFilters, type MediaSearch } from '@/lib/media-filters'
import { projectMediaMarks } from '@/lib/media-mark-cache'
import { playbackMutationKeys } from '@/lib/playback-keys'

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
      (await readAfterWrites(client, [markMutationKeys.all], signal, () => getAuthors(signal))).map(
        (author) => projectAuthorMarks(client, author),
      ),
  })
}

export function authorQuery(author: string) {
  return queryOptions({
    queryKey: ['author', author],
    queryFn: async ({ signal, client }) =>
      projectAuthorMarks(
        client,
        await readAfterWrites(client, [markMutationKeys.author(author)], signal, () =>
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
        await readAfterWrites(client, [markMutationKeys.author(author)], signal, () =>
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
        await readAfterWrites(
          client,
          [
            markMutationKeys.post(author, postId),
            markMutationKeys.bulk(author),
            playbackMutationKeys.post(author, postId),
          ],
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

export function mediaQuery(author: string, search: MediaSearch) {
  return queryOptions({
    queryKey: ['media', author, toMediaFilters(search)],
    queryFn: async ({ signal, client }) =>
      projectMediaMarks(
        client,
        author,
        await readAfterWrites(
          client,
          [markMutationKeys.author(author), playbackMutationKeys.author(author)],
          signal,
          () => getMedia(author, search, signal),
        ),
      ),
  })
}

export function usePostList(author: string, filters: Filters, active = true) {
  return useQuery({
    ...postsQuery(author, filters),
    subscribed: active,
    enabled: active,
    placeholderData: (previous, query) => (query?.queryKey[1] === author ? previous : undefined),
  })
}
