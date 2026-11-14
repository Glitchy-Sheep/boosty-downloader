import type { QueryClient } from '@tanstack/react-query'

import type { MediaItem } from '@/lib/api.gen'
import { postQuery } from '@/lib/queries'

/** A position response cannot replace the body, other marks or the media inventory. */
export function acceptPosition(
  client: QueryClient,
  author: string,
  postId: string,
  saved: MediaItem,
): void {
  client.setQueryData(postQuery(author, postId).queryKey, (post) => {
    if (!post) return post
    return {
      ...post,
      media: post.media.map((item) =>
        item.id === saved.id
          ? {
              ...item,
              position_s: saved.position_s,
              duration_s: saved.duration_s,
              finished: saved.finished,
            }
          : item,
      ),
    }
  })
}
