import type { QueryClient } from '@tanstack/react-query'

import type { MediaItem, MediaPage } from '@/lib/api.gen'
import { postQuery } from '@/lib/queries'

/** A position response cannot replace the body, other marks or the media inventory. */
export function acceptPosition(
  client: QueryClient,
  author: string,
  postId: string,
  saved: MediaItem,
  previousFinished: boolean | undefined,
): void {
  let finishedChanged = previousFinished === undefined || previousFinished !== saved.finished
  const patch = (item: MediaItem): MediaItem => {
    if (item.id !== saved.id || item.post_id !== postId) return item
    finishedChanged ||= item.finished !== saved.finished
    return {
      ...item,
      position_s: saved.position_s,
      duration_s: saved.duration_s,
      finished: saved.finished,
    }
  }
  client.setQueryData(postQuery(author, postId).queryKey, (post) => {
    if (!post) return post
    return {
      ...post,
      media: post.media.map(patch),
    }
  })
  client.setQueriesData<MediaPage>(
    { queryKey: ['media', author] },
    (page) => page && { ...page, items: page.items.map(patch) },
  )
  if (finishedChanged) void client.invalidateQueries({ queryKey: ['media', author] })
}
