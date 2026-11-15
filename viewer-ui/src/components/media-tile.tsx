import { cn } from 'cn'
import { AudioLines, CircleCheck, Play } from 'lucide-react'
import { memo, type ReactNode } from 'react'

import { REMOVED_MEDIA_ART, REMOVED_MEDIA_LABEL } from '@/components/removed-media'
import type { MediaItem, MediaPost } from '@/lib/api.gen'
import { mediaThumbnailPath, postThumbnailPath } from '@/lib/media-paths'
import { formatPlaybackTime } from '@/lib/playback-position'

export type MediaTileProps = {
  author: string
  item: MediaItem
  post: MediaPost
  active: boolean
  onOpen: (id: string) => void
  favorite: ReactNode
}

function titleOf(item: MediaItem, post: MediaPost): string {
  if (item.kind === 'audio' && item.title?.trim()) return item.title
  return post.title.trim() ? post.title : 'Untitled post'
}

function progressOf(item: MediaItem): number {
  if (!item.position_s || !item.duration_s) return 0
  return Math.min(1, Math.max(0, item.position_s / item.duration_s))
}

/** The open action and the favorite control are separate keyboard targets. */
export const MediaTile = memo(function MediaTile({
  author,
  item,
  post,
  active,
  onOpen,
  favorite,
}: MediaTileProps) {
  const track = item.kind === 'audio'
  const art = track
    ? post.cover_path && postThumbnailPath(author, item.post_id)
    : mediaThumbnailPath(author, item)
  const title = titleOf(item, post)
  const action = track ? 'Play' : 'Open'
  const label = `${action} ${title}${item.removed ? REMOVED_MEDIA_LABEL : ''}`
  const progress = progressOf(item)

  return (
    <div
      data-media-tile={item.id}
      data-removed={item.removed ? '' : undefined}
      className="group/tile group/removed relative aspect-square"
    >
      <button
        type="button"
        data-media-id={item.id}
        onClick={() => {
          if (active) onOpen(item.id)
        }}
        aria-label={label}
        tabIndex={active ? 0 : -1}
        className={cn(
          'relative block size-full overflow-hidden outline-none focus-visible:z-10 focus-visible:ring-3 focus-visible:ring-ring',
          track ? 'bg-slate-900' : 'bg-muted',
        )}
      >
        <span data-art="" className={cn('absolute inset-0', item.removed && REMOVED_MEDIA_ART)}>
          {art ? (
            <img
              src={art}
              alt=""
              loading="lazy"
              decoding="async"
              draggable={false}
              className={cn(
                'size-full object-cover transition duration-300 group-hover/tile:scale-[1.04]',
                track && 'opacity-40 blur-[1px]',
              )}
            />
          ) : (
            <span className="block size-full bg-linear-to-br from-slate-600 to-slate-800" />
          )}
        </span>
        {item.kind === 'videos' && <VideoOverlay item={item} />}
        {track && (
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-3 text-center text-white">
            <AudioLines aria-hidden="true" className="size-7 drop-shadow" />
            <span className="line-clamp-2 text-[12px] leading-tight font-medium drop-shadow">
              {title}
            </span>
            {item.duration_s !== null && <Duration seconds={item.duration_s} />}
          </span>
        )}
        {progress > 0 && !item.finished && (
          <span
            data-playback-progress=""
            className="absolute inset-x-0 bottom-0 h-1 bg-black/40"
            title={`${Math.round(progress * 100)}% played`}
          >
            <span className="block h-full bg-primary" style={{ width: `${progress * 100}%` }} />
          </span>
        )}
        {item.finished && (
          <span
            className="absolute top-1.5 left-1.5 rounded-full bg-black/55 text-white"
            title="Played to the end"
          >
            <CircleCheck aria-hidden="true" className="size-4" />
          </span>
        )}
        {!track && (
          <span className="pointer-events-none absolute inset-x-0 bottom-0 bg-linear-to-t from-black/75 to-transparent px-2 pt-6 pb-2 text-left text-[12px] leading-tight font-medium text-white opacity-0 transition-opacity group-hover/tile:opacity-100 group-focus-within/tile:opacity-100">
            <span className="line-clamp-2 rounded-sm bg-black/70 px-1 py-0.5">{title}</span>
          </span>
        )}
      </button>
      <div
        className={cn(
          'absolute top-1.5 right-1.5 z-10',
          !post.favorite &&
            'pointer-events-none opacity-0 group-hover/tile:pointer-events-auto group-hover/tile:opacity-100 group-focus-within/tile:pointer-events-auto group-focus-within/tile:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100',
        )}
      >
        {favorite}
      </div>
    </div>
  )
})

function VideoOverlay({ item }: { item: MediaItem }) {
  return (
    <>
      <span className="absolute inset-0 grid place-items-center">
        <span className="grid size-10 place-items-center rounded-full bg-black/45 text-white backdrop-blur-sm transition group-hover/tile:scale-110">
          <Play aria-hidden="true" className="size-4 translate-x-px" fill="currentColor" />
        </span>
      </span>
      {item.duration_s !== null && (
        <Duration
          seconds={item.duration_s}
          className="transition-opacity group-hover/tile:opacity-0 group-focus-within/tile:opacity-0"
        />
      )}
    </>
  )
}

function Duration({ seconds, className }: { seconds: number; className?: string }) {
  return (
    <span
      className={cn(
        'absolute bottom-2 left-2 rounded bg-black/60 px-1.5 py-0.5 text-[11.5px] font-medium text-white tabular-nums',
        className,
      )}
    >
      {formatPlaybackTime(seconds)}
    </span>
  )
}
