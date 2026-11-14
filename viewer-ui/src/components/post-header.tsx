import { cn } from 'cn'
import { ArrowUpRight, CalendarDays, Heart, Lock } from 'lucide-react'

import type { PostDetail } from '@/lib/api.gen'
import { formatDate } from '@/lib/dates'
import { displayedPostTitle, safeHttpUrl } from '@/lib/post-presentation'

type PostHeaderProps = {
  post: PostDetail
  selectedTag?: string
  favoritePending: boolean
  favoriteError: string | null
  onFavorite: () => void
  onTag: (tag: string) => void
}

export function PostHeader({
  post,
  selectedTag,
  favoritePending,
  favoriteError,
  onFavorite,
  onTag,
}: PostHeaderProps) {
  const boostyUrl = safeHttpUrl(post.boosty_url)
  const favoriteLabel = post.favorite ? 'Remove from favorites' : 'Add to favorites'

  return (
    <header>
      <h1 className="text-[23px] leading-[1.22] font-semibold tracking-[-0.015em] wrap-anywhere text-balance @2xl/main:text-[28px]">
        {displayedPostTitle(post.title)}
      </h1>
      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <CalendarDays aria-hidden="true" className="size-3.5" />
          <time dateTime={post.created_at}>{formatDate(post.created_at)}</time>
        </span>
        {[...new Set(post.tags)].map((tag) => (
          <button
            key={tag}
            type="button"
            aria-pressed={selectedTag === tag}
            onClick={() => onTag(tag)}
            className="min-h-6 max-w-full rounded-md bg-secondary px-2 py-0.5 text-[12px] wrap-anywhere outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:bg-primary-soft aria-pressed:text-primary"
          >
            #{tag}
          </button>
        ))}
        {boostyUrl && (
          <a
            href={boostyUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 rounded-sm font-medium outline-none transition-colors hover:text-primary focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Boosty <ArrowUpRight aria-hidden="true" className="size-3.5" />
          </a>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {post.access === 'locked' ? (
            <span className="inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[12.5px]">
              <Lock aria-hidden="true" className="size-3.5" />
              Locked
            </span>
          ) : (
            <button
              type="button"
              onClick={onFavorite}
              disabled={favoritePending}
              aria-label={favoriteLabel}
              aria-pressed={post.favorite}
              title={favoriteLabel}
              className={cn(
                'grid size-8 place-items-center rounded-lg outline-none transition-colors hover:bg-muted hover:text-rose-500 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-wait disabled:opacity-50',
                post.favorite && 'text-rose-500',
              )}
            >
              <Heart
                aria-hidden="true"
                className="size-4"
                fill={post.favorite ? 'currentColor' : 'none'}
              />
            </button>
          )}
        </div>
      </div>
      {favoriteError && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {favoriteError}
        </p>
      )}
    </header>
  )
}
