import { cn } from 'cn'
import { AudioLines, FileText, Film, ImageIcon, Lock, Paperclip, type LucideIcon } from 'lucide-react'
import { createElement, useState } from 'react'

import type { MediaCounts, PostRow } from '@/lib/api.gen'

function mainIcon(counts: MediaCounts): LucideIcon {
  if (counts.videos > 0) return Film
  if (counts.audio > 0) return AudioLines
  if (counts.images > 0) return ImageIcon
  if (counts.files > 0) return Paperclip
  return FileText
}

type ThumbnailProps = { author: string; post: PostRow; className?: string }

/** The thumbnail endpoint selects a saved image, preview or locked teaser. */
export function PostThumbnail({ author, post, className }: ThumbnailProps) {
  const source = `/thumbs/${encodeURIComponent(author)}/${encodeURIComponent(post.id)}`
  return <ThumbnailImage key={source} source={source} post={post} className={className} />
}

function ThumbnailImage({ source, post, className }: Omit<ThumbnailProps, 'author'> & { source: string }) {
  const [failed, setFailed] = useState(false)
  const locked = post.access === 'locked'

  return (
    <div aria-hidden="true" className={cn('relative aspect-video shrink-0 overflow-hidden rounded-[6px] bg-muted after:pointer-events-none after:absolute after:inset-0 after:rounded-[inherit] after:ring-1 after:ring-foreground/8 after:ring-inset', className ?? 'w-24')}>
      <div className="grid size-full place-items-center bg-linear-to-br from-muted to-card text-muted-foreground">
        {createElement(mainIcon(post.counts), { className: cn('size-5', locked && 'opacity-40'), strokeWidth: 1.6 })}
      </div>
      {!failed && (
        <img
          src={source}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailed(true)}
          className={cn('absolute inset-0 size-full object-cover', locked && 'opacity-35 saturate-50')}
        />
      )}
      {locked && (
        <div className="absolute inset-0 grid place-items-center">
          <span className="grid size-6 place-items-center rounded-full bg-background/75 text-foreground backdrop-blur-sm"><Lock className="size-3" /></span>
        </div>
      )}
    </div>
  )
}
