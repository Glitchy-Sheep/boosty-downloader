import { cn } from 'cn'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import type { MouseEvent } from 'react'

import type { PostRow } from '@/lib/api.gen'
import { formatDate } from '@/lib/dates'
import type { PostNeighbours } from '@/lib/post-neighbours'
import { displayedPostTitle } from '@/lib/post-presentation'

type PostPagerProps = PostNeighbours & {
  pending: boolean
  onPost: (id: string) => void
  postHref: (id: string) => string
}

export function PostPager({ previous, next, pending, onPost, postHref }: PostPagerProps) {
  if (pending)
    return (
      <p role="status" className="mt-10 text-sm text-muted-foreground">
        Updating post navigation...
      </p>
    )
  if (!previous && !next) return null
  return (
    <nav
      aria-label="Post navigation"
      className="mt-10 grid gap-3 @md/main:mt-14 @md/main:grid-cols-2"
    >
      {previous ? (
        <PagerLink
          post={previous}
          direction="previous"
          onPost={onPost}
          href={postHref(previous.id)}
        />
      ) : (
        <span className="hidden @md/main:block" />
      )}
      {next && <PagerLink post={next} direction="next" onPost={onPost} href={postHref(next.id)} />}
    </nav>
  )
}

type PagerLinkProps = {
  post: PostRow
  direction: 'previous' | 'next'
  onPost: (id: string) => void
  href: string
}

function PagerLink({ post, direction, onPost, href }: PagerLinkProps) {
  const isNext = direction === 'next'
  const label = isNext ? 'Next' : 'Previous'
  const title = displayedPostTitle(post.title)
  const select = (event: MouseEvent<HTMLAnchorElement>): void => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return
    event.preventDefault()
    onPost(post.id)
  }
  return (
    <a
      href={href}
      onClick={select}
      aria-label={`${label}: ${title}`}
      className={cn(
        'group flex flex-col gap-1.5 rounded-[10px] border bg-card p-4 outline-none transition-colors hover:border-primary/50 focus-visible:ring-3 focus-visible:ring-ring/50',
        isNext && '@md/main:items-end @md/main:text-right',
      )}
    >
      <span className="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground transition-colors group-hover:text-primary">
        {!isNext && <ArrowLeft aria-hidden="true" className="size-3.5" />}
        {label}
        {isNext && <ArrowRight aria-hidden="true" className="size-3.5" />}
      </span>
      <span className="line-clamp-2 text-[14px] leading-snug font-medium wrap-anywhere">
        {title}
      </span>
      <time dateTime={post.created_at} className="text-[12px] text-muted-foreground">
        {formatDate(post.created_at)}
      </time>
    </a>
  )
}
