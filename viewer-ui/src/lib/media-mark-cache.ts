import type { QueryClient } from '@tanstack/react-query'

import type { MediaPage, MediaPost } from '@/lib/api.gen'
import { pendingPostMarks } from '@/lib/mark-state'
import { applyMediaMark, type PostMarkChange, type PostMarkRequest } from '@/lib/post-marks'

function withPendingMarks(
  postId: string,
  post: MediaPost,
  pending: readonly PostMarkRequest[],
): MediaPost {
  return pending.reduce(
    (current, request) =>
      request.postId === postId ? applyMediaMark(current, request.change) : current,
    post,
  )
}

export function cachedMediaPost(
  client: QueryClient,
  author: string,
  postId: string,
): MediaPost | undefined {
  const pending = pendingPostMarks(client, author)
  for (const [, page] of client.getQueriesData<MediaPage>({ queryKey: ['media', author] })) {
    const post = page?.posts[postId]
    if (post) return withPendingMarks(postId, post, pending)
  }
  const source = pending.find((request) => request.postId === postId)?.source
  if (source?.kind === 'media') return withPendingMarks(postId, source.post, pending)
  return undefined
}

/** Media membership and counts stay authoritative; only shared mark fields are projected. */
export function projectMediaMarks(client: QueryClient, author: string, page: MediaPage): MediaPage {
  const pending = pendingPostMarks(client, author)
  if (!pending.length) return page
  const posts = Object.fromEntries(
    Object.entries(page.posts).map(([postId, post]) => {
      for (const request of pending) {
        if (request.postId === postId && request.source.kind === 'media') request.source.post = post
      }
      return [postId, withPendingMarks(postId, post, pending)]
    }),
  )
  return { ...page, posts }
}

export function patchMediaMarks(
  client: QueryClient,
  request: PostMarkRequest,
  change: PostMarkChange,
  direction: 'next' | 'previous' = 'next',
): void {
  client.setQueriesData<MediaPage>({ queryKey: ['media', request.author] }, (page) => {
    const post = page?.posts[request.postId]
    if (!page || !post) return page
    return {
      ...page,
      posts: { ...page.posts, [request.postId]: applyMediaMark(post, change, direction) },
    }
  })
}
