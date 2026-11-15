import { cn } from 'cn'
import { AudioLines, Film, ImageIcon, Lock, Paperclip, type LucideIcon } from 'lucide-react'
import { memo, useId, type MouseEvent } from 'react'

import { Highlighted } from '@/components/highlighted'
import { FavoriteButton } from '@/components/favorite-button'
import { PostThumbnail } from '@/components/post-thumbnail'
import { UpdatedBadge } from '@/components/updated-badge'
import type { MediaCounts, PostRow as PostSummary } from '@/lib/api.gen'
import { formatDay } from '@/lib/dates'
import { plural } from '@/lib/format'
import { isPostUnread } from '@/lib/post-marks'

type MediaLabel = { kind: keyof MediaCounts; icon: LucideIcon; one: string; many: string }
const MEDIA: readonly MediaLabel[] = [
  { kind: 'videos', icon: Film, one: 'video', many: 'videos' },
  { kind: 'images', icon: ImageIcon, one: 'photo', many: 'photos' },
  { kind: 'files', icon: Paperclip, one: 'file', many: 'files' },
  { kind: 'audio', icon: AudioLines, one: 'audio track', many: 'audio tracks' },
]

type RowFavorite = { toggle: () => void; pending: boolean; error: string | null }
export type PostRowProps = {
  author: string
  post: PostSummary
  current: boolean
  href: string
  onSelect: (id: string) => void
  favorite: RowFavorite
}

function stateDescription(post: PostSummary): string {
  const states: string[] = []
  if (post.access === 'open') states.push(isPostUnread(post) ? 'Unseen' : 'Seen')
  else if (post.seen) states.push('Seen')
  if (post.access === 'locked') states.push('Locked')
  if (post.favorite) states.push('Favorite')
  if (post.updated) states.push('Updated since seen')
  if (post.missing_media > 0) states.push(`${plural(post.missing_media, 'missing piece')}`)
  return `${states.join('. ')}.`
}

/** Rows share geometry through the virtual list's CSS properties. */
export const PostRow = memo(function PostRow({
  author,
  post,
  current,
  href,
  onSelect,
  favorite,
}: PostRowProps) {
  const id = useId()
  const locked = post.access === 'locked'
  const unread = isPostUnread(post)
  const snippet = post.match?.text
  const select = (event: MouseEvent<HTMLAnchorElement>): void => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return
    event.preventDefault()
    onSelect(post.id)
  }

  return (
    <div data-post-row={post.id} className="group/row relative h-full">
      <a
        href={href}
        onClick={select}
        data-post-id={post.id}
        aria-current={current ? 'page' : undefined}
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-state`}
        className={cn(
          'post-row relative flex h-full outline-none transition-colors hover:bg-muted/70 focus-visible:bg-muted',
          current && 'bg-primary-soft hover:bg-primary-soft',
        )}
      >
        {current && (
          <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-primary" />
        )}
        <div className="post-row-cover relative shrink-0">
          <PostThumbnail author={author} post={post} className="size-full" />
          {post.updated && <UpdatedBadge className="absolute top-1 left-1" />}
        </div>
        <div className="flex min-w-0 flex-1 flex-col justify-between">
          <div className="min-w-0">
            <div
              id={`${id}-title`}
              className={cn(
                'post-row-title wrap-anywhere font-semibold',
                snippet && 'post-row-title-short',
                unread ? 'text-foreground' : 'text-muted-foreground',
              )}
            >
              {unread && (
                <span
                  aria-hidden="true"
                  className="mr-1.5 mb-[2px] inline-block size-[7px] rounded-full bg-primary align-middle"
                />
              )}
              <PostTitle post={post} />
            </div>
            {snippet && (
              <p className="mt-1 line-clamp-2 text-[12.5px] leading-4 wrap-anywhere text-muted-foreground">
                <Highlighted runs={snippet} />
              </p>
            )}
          </div>
          <div
            className={cn(
              'flex h-4 min-w-0 items-center gap-2.5 overflow-hidden text-[12px] text-muted-foreground',
              !locked && 'pr-6',
            )}
          >
            <time dateTime={post.created_at} className="shrink-0">
              {formatDay(post.created_at)}
            </time>
            {favorite.error ? (
              <span
                role="alert"
                title={favorite.error}
                className="min-w-0 truncate text-destructive"
              >
                {favorite.error}
              </span>
            ) : (
              <RowContent post={post} />
            )}
            {post.missing_media > 0 && (
              <span
                title={plural(post.missing_media, 'missing piece')}
                className="ml-auto shrink-0 text-[11px]"
              >
                {post.missing_media} missing
              </span>
            )}
          </div>
        </div>
        <span id={`${id}-state`} hidden>
          {stateDescription(post)}
        </span>
      </a>
      {!locked && (
        <FavoriteButton
          favorite={post.favorite}
          pending={favorite.pending}
          onToggle={favorite.toggle}
          iconClassName="size-3.5"
          className={cn(
            'absolute right-(--row-pad-x) bottom-2 size-6',
            !post.favorite &&
              'pointer-events-none opacity-0 group-hover/row:pointer-events-auto group-hover/row:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100',
          )}
        />
      )}
    </div>
  )
})

function RowContent({ post }: { post: PostSummary }) {
  if (post.access === 'locked') return <LockedTier tier={post.tier} />
  return <MediaIcons counts={post.counts} />
}

function PostTitle({ post }: { post: PostSummary }) {
  if (!post.title.trim()) return 'Untitled post'
  return <Highlighted runs={post.match?.title} text={post.title} />
}

function LockedTier({ tier }: { tier: string | null }) {
  return (
    <span className="flex min-w-0 items-center gap-1">
      <Lock aria-hidden="true" className="size-3 shrink-0" />
      <span className="truncate">{tier || 'Locked post'}</span>
    </span>
  )
}

function MediaIcons({ counts }: { counts: MediaCounts }) {
  return (
    <span className="flex min-w-0 items-center gap-2 overflow-hidden">
      {MEDIA.filter(({ kind }) => counts[kind] > 0).map(({ kind, icon: Icon, one, many }) => (
        <span
          key={kind}
          title={plural(counts[kind], one, many)}
          className="relative inline-flex shrink-0 items-center gap-[3px] tabular-nums"
        >
          <Icon aria-hidden="true" className="size-3" />
          <span aria-hidden="true">{counts[kind]}</span>
          <span className="sr-only">{plural(counts[kind], one, many)}</span>
        </span>
      ))}
    </span>
  )
}
