import { useQuery } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import { useRef, useState } from 'react'

import { FavoriteButton } from '@/components/favorite-button'
import { AudioList } from '@/components/audio-list'
import { FileList } from '@/components/file-list'
import { MediaGrid, type MediaGridHandle } from '@/components/media-grid'
import { MediaToolbar, type MediaFilterUpdate } from '@/components/media-toolbar'
import { MediaViewer } from '@/components/media-viewer'
import { LoadError } from '@/components/route-screens'
import { useFavorite } from '@/hooks/use-favorite'
import { useRetainedData } from '@/hooks/use-retained-data'
import type { MediaPage, MediaPost } from '@/lib/api.gen'
import { useTabActive } from '@/lib/author-tab'
import { NO_FILTERS } from '@/lib/filters'
import { mediaSearchParams, type MediaSearch } from '@/lib/media-filters'
import {
  canCloseMediaViewerWithBack,
  closeMediaViewerState,
  mediaViewerScope,
  openMediaViewerState,
  stepMediaViewerState,
} from '@/lib/media-viewer-history'
import { mediaQuery } from '@/lib/queries'
import { usePlayerStore } from '@/lib/player'

export function MediaScreen({ author, filters }: { author: string; filters: MediaSearch }) {
  const active = useTabActive()
  const router = useRouter()
  const player = usePlayerStore()
  const query = useQuery({ ...mediaQuery(author, filters), enabled: active, subscribed: active })
  const data = useRetainedData(query.data)
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null)
  const grid = useRef<MediaGridHandle>(null)
  const scope = mediaViewerScope(author, filters)

  const changeFilters = (update: MediaFilterUpdate): void => {
    if (!active) return
    void router.navigate({
      to: '/a/$author/media',
      params: { author },
      search: (previous) => ({
        ...previous,
        ...(typeof update === 'function' ? update(previous) : update),
        open: undefined,
      }),
    })
  }
  const show = (id: string): void => {
    if (!active) return
    const item = data?.items.find((candidate) => candidate.id === id)
    if (data && item?.kind === 'audio') {
      player.start(author, data, id)
      return
    }
    const step = Boolean(filters.open)
    void router.navigate({
      to: '/a/$author/media',
      params: { author },
      search: { ...filters, open: id },
      replace: step,
      state: (previous) =>
        step ? stepMediaViewerState(previous, scope) : openMediaViewerState(previous, scope),
    })
  }
  const close = (): void => {
    if (!active) return
    if (canCloseMediaViewerWithBack(router.history.location.state, scope)) {
      router.history.back()
      return
    }
    void router.navigate({
      to: '/a/$author/media',
      params: { author },
      search: { ...filters, open: undefined },
      replace: true,
      state: closeMediaViewerState,
    })
  }

  const renderMedia = (page: MediaPage) => {
    const props = { author, page, scroller, active, listKey: mediaSearchParams(filters).toString() }
    switch (filters.view) {
      case 'audio':
        return <AudioList {...props} />
      case 'files':
        return <FileList {...props} />
      default:
        return (
          <MediaGrid
            {...props}
            ref={grid}
            onOpen={show}
            renderFavorite={(postId) => {
              const post = page.posts[postId]
              return post && <MediaFavorite author={author} postId={postId} post={post} />
            }}
          />
        )
    }
  }

  return (
    <section aria-label="Author media" className="flex h-full min-h-0 flex-col">
      <MediaToolbar
        filters={filters}
        counts={data?.counts}
        updating={query.isFetching}
        onChange={changeFilters}
      />
      {query.isError && <LoadError error={query.error} />}
      {!data && !query.isError && (
        <p role="status" className="p-8 text-muted-foreground">
          Loading media...
        </p>
      )}
      <div
        ref={setScroller}
        data-media-scroller=""
        className="min-h-0 flex-1 overflow-y-auto [overflow-anchor:none]"
      >
        {data && (
          <div className="mx-auto w-full max-w-[1400px] px-2 pt-1 pb-10 md:px-6">
            {!data.items.length && (
              <p role="status" className="p-8 text-muted-foreground">
                No downloaded media in this view.
              </p>
            )}
            {renderMedia(data)}
          </div>
        )}
      </div>
      {data && (
        <MediaViewer
          author={author}
          data={data}
          openId={filters.open}
          active={active}
          onShow={show}
          onClose={close}
          onRestoreFocus={async (id) => grid.current?.focusItem(id) ?? false}
          postHref={(id) => `/a/${encodeURIComponent(author)}/p/${encodeURIComponent(id)}`}
          onPost={(postId) => {
            void router.navigate({
              to: '/a/$author/p/$postId',
              params: { author, postId },
              search: { ...NO_FILTERS },
            })
          }}
        />
      )}
    </section>
  )
}

function MediaFavorite({
  author,
  postId,
  post,
}: {
  author: string
  postId: string
  post: MediaPost
}) {
  const mark = useFavorite(author, postId)
  if (post.access === 'locked') return null
  return (
    <>
      <FavoriteButton
        favorite={post.favorite}
        pending={mark.pending}
        onToggle={mark.toggle}
        className="size-7 rounded-full bg-black/55 text-white hover:bg-black/75"
        iconClassName="size-4"
      />
      {mark.error && (
        <p
          role="alert"
          className="absolute top-8 right-0 z-20 w-44 rounded-md border bg-popover p-2 text-xs text-popover-foreground shadow-lg"
        >
          {mark.error}
        </p>
      )}
    </>
  )
}
