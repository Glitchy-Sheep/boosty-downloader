import { ArrowUpRight, CalendarDays, FolderOpen, Lock } from 'lucide-react'

import { FavoriteButton } from '@/components/favorite-button'
import { FileActionButton } from '@/components/file-actions'
import { SeenButton } from '@/components/seen-button'
import { UpdatedBadge } from '@/components/updated-badge'
import { usePostFolderAction } from '@/hooks/use-file-actions'
import type { PostDetail } from '@/lib/api.gen'
import { formatDate } from '@/lib/dates'
import { isPostUnread } from '@/lib/post-marks'
import { displayedPostTitle, safeHttpUrl } from '@/lib/post-presentation'

type PostHeaderProps = {
  author: string
  post: PostDetail
  selectedTag?: string | undefined
  favoritePending: boolean
  favoriteError: string | null
  onFavorite: () => void
  seenPending: boolean
  seenError: string | null
  onSeen: () => void
  onTag: (tag: string) => void
}

export function PostHeader({
  author,
  post,
  selectedTag,
  favoritePending,
  favoriteError,
  onFavorite,
  seenPending,
  seenError,
  onSeen,
  onTag,
}: PostHeaderProps) {
  const boostyUrl = safeHttpUrl(post.boosty_url)
  const folder = usePostFolderAction(author, post)
  const errors = [...new Set([favoriteError, seenError].filter((error) => error !== null))]

  return (
    <header>
      <h1 className="text-[23px] leading-[1.22] font-semibold tracking-[-0.015em] wrap-anywhere text-balance @2xl/main:text-[28px]">
        {displayedPostTitle(post.title)}
      </h1>
      {post.updated && <UpdatedBadge className="mt-2" />}
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
          {folder && <FileActionButton key={post.id} action={folder} icon={FolderOpen} />}
          {post.access === 'locked' ? (
            <span className="inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[12.5px]">
              <Lock aria-hidden="true" className="size-3.5" />
              Locked
            </span>
          ) : (
            <>
              <FavoriteButton
                favorite={post.favorite}
                pending={favoritePending}
                onToggle={onFavorite}
                shortcut
                className="size-8 hover:bg-muted"
              />
              <SeenButton seen={!isPostUnread(post)} pending={seenPending} onToggle={onSeen} />
            </>
          )}
        </div>
      </div>
      {errors.map((error) => (
        <p key={error} role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ))}
    </header>
  )
}
