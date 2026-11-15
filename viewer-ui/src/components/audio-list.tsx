import { Link } from '@tanstack/react-router'
import { cn } from 'cn'
import { AudioLines, CircleCheck, Pause, Play } from 'lucide-react'

import { FavoriteButton } from '@/components/favorite-button'
import { FileActions } from '@/components/file-actions'
import { FileContextMenu } from '@/components/file-context-menu'
import { MediaSection, REMOVED_MEDIA_LABEL } from '@/components/removed-media'
import { useFavorite } from '@/hooks/use-favorite'
import { useMediaFileActions } from '@/hooks/use-file-actions'
import { useMediaList, type MediaListProps } from '@/hooks/use-media-list'
import type { MediaItem, MediaPost } from '@/lib/api.gen'
import { formatDate } from '@/lib/dates'
import { displayFileName, fileNameOnDisk } from '@/lib/file-presentation'
import { NO_FILTERS } from '@/lib/filters'
import { postThumbnailPath } from '@/lib/media-paths'
import { formatPlaybackTime } from '@/lib/playback-position'
import { currentTrack, usePlayerState, usePlayerStore } from '@/lib/player'

const AUDIO_ROW_HEIGHT = 96
const REMOVED_COVER =
  'opacity-35 transition-opacity group-hover/removed:opacity-100 group-focus-within/removed:opacity-100 group-has-[[aria-expanded=true]]/removed:opacity-100 group-data-[state=open]/removed:opacity-100'

export function AudioList(props: MediaListProps) {
  const { author, page, active } = props
  const list = useMediaList(props, AUDIO_ROW_HEIGHT)
  const store = usePlayerStore()
  return (
    <div
      data-audio-list=""
      inert={!active}
      className="relative w-full"
      style={{ height: list.height }}
    >
      {list.rows.map(({ key, start, row }) => {
        const style = { transform: `translateY(${start}px)` }
        if (row.kind !== 'item') return <MediaSection key={key} row={row} style={style} />
        const post = page.posts[row.item.post_id]
        if (!post) throw new Error(`Missing post metadata for media ${row.item.id}`)
        return (
          <div
            key={key}
            data-media-id={row.item.id}
            className="absolute top-0 left-0 w-full pb-2"
            style={{ ...style, height: AUDIO_ROW_HEIGHT }}
          >
            <AudioCard
              author={author}
              item={row.item}
              post={post}
              active={active}
              onStart={() => store.start(author, page, row.item.id)}
            />
          </div>
        )
      })}
    </div>
  )
}

type AudioCardProps = {
  author: string
  item: MediaItem
  post: MediaPost
  active: boolean
  onStart: () => void
}

function AudioCard({ author, item, post, active, onStart }: AudioCardProps) {
  const state = usePlayerState()
  const store = usePlayerStore()
  const { actions, local } = useMediaFileActions(author, item, { onOpen: () => store.pause() })
  const visibleActions = local ? actions : actions.filter((action) => action.id === 'download')
  const fileLabel = displayFileName(fileNameOnDisk(item))
  const favorite = useFavorite(author, item.post_id)
  const current = state?.author === author && currentTrack(state)?.id === item.id
  const playing = current && state.playing
  const title = item.title?.trim() || post.title || 'Untitled track'
  const dimmed = item.removed && !playing
  const coverOpacity = playing ? 'opacity-100' : 'opacity-70'
  const played = item.duration_s ? (item.position_s ?? 0) / item.duration_s : 0
  const progress = item.finished ? 1 : Math.min(1, Math.max(0, played))
  const play = (): void => {
    if (!active) return
    if (!current) {
      onStart()
      return
    }
    void store.toggle()
  }
  return (
    <FileContextMenu actions={actions} enabled={local} active={active} label={fileLabel}>
      <div
        data-playing={playing ? '' : undefined}
        data-removed={item.removed ? '' : undefined}
        className={cn(
          'group/removed flex h-full items-center gap-2 rounded-[10px] border bg-card px-2 sm:gap-3 sm:px-3',
          current && 'border-primary/50 bg-primary-soft',
        )}
      >
        <button
          type="button"
          onClick={play}
          aria-label={`${playing ? 'Pause' : 'Play'} ${title}${item.removed ? REMOVED_MEDIA_LABEL : ''}`}
          className="group relative grid size-12 shrink-0 place-items-center overflow-hidden rounded-lg bg-muted text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 sm:size-14"
        >
          <span
            data-art=""
            className={cn(
              'absolute inset-0 grid place-items-center',
              dimmed ? REMOVED_COVER : coverOpacity,
            )}
          >
            {post.cover_path ? (
              <img
                src={postThumbnailPath(author, item.post_id)}
                alt=""
                loading="lazy"
                decoding="async"
                className="size-full object-cover"
              />
            ) : (
              <AudioLines aria-hidden="true" className="size-5" />
            )}
          </span>
          <span className="relative grid size-8 place-items-center rounded-full bg-primary text-primary-foreground shadow">
            {playing ? (
              <Pause aria-hidden="true" className="size-3.5" fill="currentColor" />
            ) : (
              <Play aria-hidden="true" className="size-3.5 translate-x-px" fill="currentColor" />
            )}
          </span>
        </button>
        <div className="min-w-0 flex-1">
          <div
            title={title}
            className={cn(
              'relative truncate text-[14px] font-medium',
              dimmed && 'text-muted-foreground',
            )}
          >
            {title}
            <span className="sr-only">{item.removed ? REMOVED_MEDIA_LABEL : ''}</span>
          </div>
          {item.artist && (
            <div className="truncate text-[12px] text-muted-foreground" title={item.artist}>
              {item.artist}
            </div>
          )}
          <div className="flex min-w-0 gap-1 text-[11px] text-muted-foreground">
            <Link
              to="/a/$author/p/$postId"
              params={{ author, postId: item.post_id }}
              search={NO_FILTERS}
              className="min-w-0 truncate hover:text-foreground"
              title={post.title}
            >
              {post.title}
            </Link>
            <span className="shrink-0">· {formatDate(item.created_at)}</span>
          </div>
          {favorite.error && (
            <p
              role="status"
              title={favorite.error}
              className="truncate text-[11px] text-destructive"
            >
              {favorite.error}
            </p>
          )}
          <div
            className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted"
            title={`${Math.round(progress * 100)}% played`}
          >
            <div
              className={cn(
                'h-full rounded-full',
                item.finished ? 'bg-muted-foreground/40' : 'bg-primary',
              )}
              style={{ width: `${progress * 100}%` }}
            />
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1 text-[11px] text-muted-foreground tabular-nums">
          <span className="flex items-center gap-1">
            {item.finished && <CircleCheck className="size-3.5" aria-label="Played to the end" />}
            {item.duration_s !== null && formatPlaybackTime(item.duration_s)}
          </span>
          <div className="flex items-center gap-1">
            {post.access === 'open' && (
              <FavoriteButton
                favorite={post.favorite}
                pending={favorite.pending || !active}
                onToggle={favorite.toggle}
                className="size-7"
              />
            )}
            <FileActions actions={visibleActions} mode="menu" label={fileLabel} active={active} />
          </div>
        </div>
      </div>
    </FileContextMenu>
  )
}
