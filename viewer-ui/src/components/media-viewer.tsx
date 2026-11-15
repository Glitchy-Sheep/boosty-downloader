import { useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, ChevronLeft, ChevronRight, X } from 'lucide-react'
import { Dialog } from 'radix-ui'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type MouseEvent,
} from 'react'

import { FavoriteButton } from '@/components/favorite-button'
import { FileActions } from '@/components/file-actions'
import { useFileNoticeHost, useMediaFileActions } from '@/hooks/use-file-actions'
import { useFavorite } from '@/hooks/use-favorite'
import { usePostPlayback, type SavePosition } from '@/hooks/use-post-playback'
import type { MediaItem, MediaPage, MediaPost } from '@/lib/api.gen'
import { formatDate } from '@/lib/dates'
import { displayFileName, fileNameOnDisk } from '@/lib/file-presentation'
import { mediaPath, mediaThumbnailPath } from '@/lib/media-paths'
import { saveMediaPosition } from '@/lib/playback-mutations'

type MediaViewerProps = {
  author: string
  data: MediaPage
  openId: string | undefined
  active: boolean
  onShow: (id: string) => void
  onClose: () => void
  onRestoreFocus: (id: string) => Promise<boolean>
  postHref: (postId: string) => string
  onPost: (postId: string) => void
}

/** Fullscreen photos and videos follow the visible list's canonical order. */
export function MediaViewer({
  author,
  data,
  openId,
  active,
  onShow,
  onClose,
  onRestoreFocus,
  postHref,
  onPost,
}: MediaViewerProps) {
  const items = data.items.filter((item) => item.kind === 'images' || item.kind === 'videos')
  const index = items.findIndex((item) => item.id === openId)
  const item = items[index]
  const post = item && data.posts[item.post_id]
  const previous = items[index - 1]
  const next = items[index + 1]
  const content = useRef<HTMLDivElement>(null)
  const noticeHost = useFileNoticeHost()
  const lastShown = useRef<string | undefined>(undefined)
  const latest = useRef({ active, onRestoreFocus })
  useLayoutEffect(() => {
    latest.current = { active, onRestoreFocus }
    if (active && item) lastShown.current = item.id
  }, [active, item, onRestoreFocus])
  const previousImage = previous?.kind === 'images' ? mediaPath(author, previous.path) : undefined
  const nextImage = next?.kind === 'images' ? mediaPath(author, next.path) : undefined
  const shownId = item?.id
  useEffect(() => {
    if (!active || !shownId) return
    for (const path of [previousImage, nextImage]) {
      if (path) new Image().src = path
    }
  }, [active, shownId, previousImage, nextImage])

  const move = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (!active || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
    if (event.target instanceof HTMLMediaElement) return
    if (!(event.target instanceof Node) || !event.currentTarget.contains(event.target)) return
    if (event.key === 'ArrowLeft' && previous) onShow(previous.id)
    else if (event.key === 'ArrowRight' && next) onShow(next.id)
    else return
    event.preventDefault()
  }

  return (
    <Dialog.Root
      open={active && Boolean(item && post)}
      onOpenChange={(open) => {
        if (!open && active) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/95" />
        {active && item && post && (
          <Dialog.Content
            ref={content}
            aria-describedby={undefined}
            onKeyDown={move}
            onOpenAutoFocus={(event) => {
              event.preventDefault()
              content.current?.focus()
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              const id = lastShown.current
              if (latest.current.active && id)
                void latest.current.onRestoreFocus(id).catch(() => false)
            }}
            className="fixed inset-0 z-50 flex flex-col text-white outline-none"
          >
            <Dialog.Title className="sr-only">Media viewer</Dialog.Title>
            <div className="flex min-h-14 shrink-0 items-center gap-3 px-3 py-2 md:px-5">
              <span className="shrink-0 text-[13px] text-white/70 tabular-nums" aria-live="polite">
                {index + 1} / {items.length}
              </span>
              <MediaPostLink
                item={item}
                post={post}
                href={postHref(item.post_id)}
                onPost={onPost}
              />
              {post.access === 'open' && <MediaFavorite author={author} item={item} post={post} />}
              <MediaFileActions
                key={item.id}
                author={author}
                item={item}
                active={active}
                onOpen={() => content.current?.querySelector('video')?.pause()}
              />
              <Dialog.Close asChild>
                <button
                  type="button"
                  aria-label="Close media viewer"
                  className="grid size-9 shrink-0 place-items-center rounded-lg outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-white"
                >
                  <X aria-hidden="true" className="size-5" />
                </button>
              </Dialog.Close>
            </div>
            <div className="relative flex min-h-0 flex-1 items-center justify-center px-2 pb-4 md:px-16">
              {item.kind === 'videos' ? (
                <MediaVideo key={item.id} author={author} item={item} />
              ) : (
                <img
                  key={item.id}
                  src={mediaPath(author, item.path)}
                  alt={item.title?.trim() || post.title.trim() || 'Saved image'}
                  draggable={false}
                  className="max-h-full max-w-full object-contain select-none"
                />
              )}
              {previous && <MediaStep direction="previous" onClick={() => onShow(previous.id)} />}
              {next && <MediaStep direction="next" onClick={() => onShow(next.id)} />}
            </div>
            <div ref={noticeHost} />
          </Dialog.Content>
        )}
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function MediaPostLink({
  item,
  post,
  href,
  onPost,
}: {
  item: MediaItem
  post: MediaPost
  href: string
  onPost: (postId: string) => void
}) {
  const openPost = (event: MouseEvent<HTMLAnchorElement>): void => {
    if (event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
      return
    event.preventDefault()
    onPost(item.post_id)
  }
  return (
    <div className="min-w-0 flex-1">
      <a
        href={href}
        onClick={openPost}
        className="inline-flex max-w-full items-center gap-1 rounded-sm text-[14px] font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-white"
      >
        <span className="truncate">{post.title.trim() || 'Untitled post'}</span>
        <ArrowUpRight aria-hidden="true" className="size-3.5 shrink-0" />
      </a>
      <div className="text-[12px] text-white/70">
        <time dateTime={item.created_at}>{formatDate(item.created_at)}</time>
        {item.removed && ' · Removed by the author'}
      </div>
    </div>
  )
}

function MediaFileActions({
  author,
  item,
  active,
  onOpen,
}: {
  author: string
  item: MediaItem
  active: boolean
  onOpen: () => void
}) {
  const { actions, local } = useMediaFileActions(author, item, { onOpen })
  const visible = local ? actions : actions.filter((action) => action.id === 'download')
  return (
    <FileActions
      actions={visible}
      mode="media"
      label={displayFileName(fileNameOnDisk(item))}
      active={active}
    />
  )
}

function MediaFavorite({
  author,
  item,
  post,
}: {
  author: string
  item: MediaItem
  post: MediaPost
}) {
  const favorite = useFavorite(author, item.post_id)
  return (
    <div className="flex max-w-48 flex-col items-center">
      <FavoriteButton
        favorite={post.favorite}
        pending={favorite.pending}
        onToggle={favorite.toggle}
        className="size-9 shrink-0 text-white/70 hover:bg-white/10"
      />
      {favorite.error && (
        <p role="alert" className="text-xs text-rose-200">
          {favorite.error}
        </p>
      )}
    </div>
  )
}

function MediaStep({
  direction,
  onClick,
}: {
  direction: 'previous' | 'next'
  onClick: () => void
}) {
  const next = direction === 'next'
  const placement = next ? 'right-2 md:right-4' : 'left-2 md:left-4'
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={next ? 'Next media' : 'Previous media'}
      className={`absolute top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-full bg-black/40 text-white outline-none backdrop-blur hover:bg-black/70 focus-visible:ring-2 focus-visible:ring-white ${placement}`}
    >
      {next ? (
        <ChevronRight aria-hidden="true" className="size-5" />
      ) : (
        <ChevronLeft aria-hidden="true" className="size-5" />
      )}
    </button>
  )
}

/** Fullscreen uses the same resume and queued-save contract as post players. */
function MediaVideo({ author, item }: { author: string; item: MediaItem }) {
  const rootRef = useRef<HTMLDivElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const client = useQueryClient()
  const savePosition = useCallback<SavePosition>(
    async (media, position, options) => {
      await saveMediaPosition(client, author, item.post_id, media, position, options.keepalive)
    },
    [client, author, item.post_id],
  )
  usePostPlayback({
    rootRef,
    author,
    postId: item.post_id,
    html: item.id,
    media: [item],
    savePosition,
  })
  useEffect(() => {
    void video.current?.play().catch(() => {})
  }, [])
  return (
    <div
      ref={rootRef}
      className="media-viewer-player flex h-full min-h-0 max-w-full flex-col items-center justify-center"
    >
      {/* oxlint-disable-next-line jsx-a11y/media-has-caption -- Saved video records do not contain caption tracks. */}
      <video
        ref={video}
        src={mediaPath(author, item.path)}
        poster={mediaThumbnailPath(author, item) ?? undefined}
        controls
        playsInline
        preload="metadata"
        aria-label={item.title?.trim() || item.filename?.trim() || 'Saved video'}
        className="min-h-0 max-h-full max-w-full rounded-lg bg-black object-contain"
      />
    </div>
  )
}
