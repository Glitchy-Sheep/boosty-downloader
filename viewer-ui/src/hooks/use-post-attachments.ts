import { useLayoutEffect, useRef, useState, type RefObject } from 'react'

import type { MediaItem } from '@/lib/api.gen'
import { attachPostAttachments, type PostAttachment } from '@/lib/post-attachments'

type PostAttachmentsOptions = {
  rootRef: RefObject<HTMLDivElement | null>
  author: string
  postId: string
  html: string
  media: readonly MediaItem[]
}

/** Playback marks do not replace attachment nodes or interrupt their menus and search hits. */
export function usePostAttachments(options: PostAttachmentsOptions) {
  const { rootRef, author, postId, html, media } = options
  const latest = useRef(media)
  const [attachments, setAttachments] = useState<PostAttachment[]>([])
  const inventory = JSON.stringify(
    media
      .filter((item) => item.kind === 'files')
      .map(({ id, post_id, path, file_type, size }) => ({ id, post_id, path, file_type, size })),
  )
  useLayoutEffect(() => {
    latest.current = media
  }, [media])
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return
    const attached = attachPostAttachments(root, author, postId, latest.current, location.origin)
    setAttachments(attached.attachments)
    return attached.cleanup
  }, [rootRef, author, postId, html, inventory])
  return { attachments, inventory }
}
