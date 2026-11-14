import { useEffect, useEffectEvent } from 'react'

import type { PostShortcutContext, PostShortcutTarget } from '@/lib/post-shortcut-context'
import { acceptsPostShortcut, postShortcut } from '@/lib/post-shortcuts'

export type PostShortcutOptions = {
  readContext: () => PostShortcutContext | null
  onPost: (target: PostShortcutTarget) => void
  onSearch: () => void
}

/** Read current navigation state for every key, including synchronous repeated presses. */
export function usePostShortcuts({ readContext, onPost, onSearch }: PostShortcutOptions): void {
  const handle = useEffectEvent((event: KeyboardEvent) => {
    const action = postShortcut(event.code)
    if (!action || !acceptsPostShortcut(event, document)) return
    const context = readContext()
    if (!context) return
    if (action === 'search') {
      event.preventDefault()
      onSearch()
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
