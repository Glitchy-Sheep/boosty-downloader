import { useLayoutEffect, useRef, type ReactNode } from 'react'

type PostPaneProps = { author: string; postId: string | undefined; children: ReactNode }

/** Keep the reader's scroll offset while responsive content changes its shape. */
export function PostPane({ author, postId, children }: PostPaneProps) {
  const ref = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    ref.current!.scrollTop = 0
  }, [author, postId])
  return (
    <section
      ref={ref}
      data-post-pane=""
      aria-label="Selected post"
      className="@container/main h-full min-h-0 min-w-0 overflow-y-auto [overflow-anchor:none]"
    >
      {children}
    </section>
  )
}
