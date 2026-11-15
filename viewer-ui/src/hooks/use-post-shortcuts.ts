import { useEffect, useEffectEvent } from 'react'

import type { PostShortcutContext, PostShortcutTarget } from '@/lib/post-shortcut-context'
import { acceptsPostShortcut, postShortcut } from '@/lib/post-shortcuts'

export type PostShortcutOptions = {
  readContext: () => PostShortcutContext | null
  onPost: (target: PostShortcutTarget) => void
  onSearch: () => void
  onSidebar?: (() => void) | undefined
  onSeen: (postId: string) => void
  onFavorite: (postId: string) => void
}

/** Read current navigation state for every key, including synchronous repeated presses. */
export function usePostShortcuts({
  readContext,
  onPost,
  onSearch,
  onSidebar,
  onSeen,
  onFavorite,
}: PostShortcutOptions): void {
  const handle = useEffectEvent((event: KeyboardEvent) => {
    const action = postShortcut(event.code)
    if (!action || !acceptsPostShortcut(event, document)) return
    const context = readContext()
    if (!context) return
    if (action === 'sidebar') {
      if (!onSidebar || event.repeat) return
      event.preventDefault()
      onSidebar()
      return
    }
    if (action === 'search') {
      event.preventDefault()
      onSearch()
      return
    }
    if (action === 'seen' || action === 'favorite') {
      if (!context.postId) return
      event.preventDefault()
      if (action === 'seen') onSeen(context.postId)
      else onFavorite(context.postId)
      return
    }
    const post = context.neighbours?.[action]
    if (!post) return
    event.preventDefault()
    onPost({ author: context.author, postId: post.id, filters: context.filters })
  })

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => handle(event)
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])
}
