import { cn } from 'cn'
import { AudioLines, Film, ImageIcon, Lock, Paperclip, type LucideIcon } from 'lucide-react'
import { memo, useId, type MouseEvent } from 'react'

import { Highlighted } from '@/components/highlighted'
import { PostThumbnail } from '@/components/post-thumbnail'
import type { MediaCounts, PostRow as PostSummary } from '@/lib/api.gen'
import { formatDay } from '@/lib/dates'
import { plural } from '@/lib/format'

type MediaLabel = { kind: keyof MediaCounts; icon: LucideIcon; one: string; many: string }
const MEDIA: readonly MediaLabel[] = [
  { kind: 'videos', icon: Film, one: 'video', many: 'videos' },
  { kind: 'images', icon: ImageIcon, one: 'photo', many: 'photos' },
  { kind: 'files', icon: Paperclip, one: 'file', many: 'files' },
  { kind: 'audio', icon: AudioLines, one: 'audio track', many: 'audio tracks' },
]

type PostRowProps = { author: string; post: PostSummary; current: boolean; href: string; onSelect: (id: string) => void }

function stateDescription(post: PostSummary): string {
  const states = [post.seen ? 'Seen' : 'Unseen']
  if (post.access === 'locked') states.push('Locked')
  if (post.favorite) states.push('Favorite')
  if (post.updated) states.push('Updated since seen')
  if (post.missing_media > 0) states.push(`${plural(post.missing_media, 'missing piece')}`)
  return `${states.join('. ')}.`
}

/** Rows share geometry through the virtual list's CSS properties. */
export const PostRow = memo(function PostRow({ author, post, current, href, onSelect }: PostRowProps) {
  const id = useId()
  const locked = post.access === 'locked'
  const snippet = post.match?.text
  const select = (event: MouseEvent<HTMLAnchorElement>): void => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    onSelect(post.id)
  }

  return (
    <a
      href={href}
      onClick={select}
      data-post-id={post.id}
      aria-current={current ? 'page' : undefined}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-state`}
      className={cn('post-row relative flex h-full outline-none transition-colors hover:bg-muted/70 focus-visible:bg-muted', current && 'bg-primary-soft hover:bg-primary-soft')}
    >
      {current && <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-primary" />}
      <PostThumbnail author={author} post={post} className="post-row-cover" />
      <div className="flex min-w-0 flex-1 flex-col justify-between">
        <div className="min-w-0">
          <div id={`${id}-title`} className={cn('post-row-title wrap-anywhere font-semibold', snippet && 'post-row-title-short', post.seen ? 'text-muted-foreground' : 'text-foreground')}>
            {!post.seen && !locked && <span aria-hidden="true" className="mr-1.5 mb-[2px] inline-block size-[7px] rounded-full bg-primary align-middle" />}
            <PostTitle post={post} />
          </div>
          {snippet && <p className="mt-1 line-clamp-2 text-[12.5px] leading-4 wrap-anywhere text-muted-foreground"><Highlighted runs={snippet} /></p>}
        </div>
        <div className="flex h-4 min-w-0 items-center gap-2.5 overflow-hidden text-[12px] text-muted-foreground">
          <time dateTime={post.created_at} className="shrink-0">{formatDay(post.created_at)}</time>
          {locked ? <LockedTier tier={post.tier} /> : <MediaIcons counts={post.counts} />}
          {post.missing_media > 0 && <span title={plural(post.missing_media, 'missing piece')} className="ml-auto shrink-0 text-[11px]">{post.missing_media} missing</span>}
        </div>
      </div>
      <span id={`${id}-state`} hidden>{stateDescription(post)}</span>
    </a>
  )
})

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
    <span className="flex min-w-0 items-center gap-2">
      {MEDIA.filter(({ kind }) => counts[kind] > 0).map(({ kind, icon: Icon, one, many }) => (
        <span key={kind} title={plural(counts[kind], one, many)} className="relative inline-flex shrink-0 items-center gap-[3px] tabular-nums">
          <Icon aria-hidden="true" className="size-3" />
          <span aria-hidden="true">{counts[kind]}</span>
          <span className="sr-only">{plural(counts[kind], one, many)}</span>
        </span>
      ))}
    </span>
  )
}
