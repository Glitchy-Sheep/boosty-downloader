import { useVirtualizer } from '@tanstack/react-virtual'
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from 'react'

import { MediaTile } from '@/components/media-tile'
import { MediaSection } from '@/components/removed-media'
import { useElementWidth } from '@/hooks/use-element-width'
import { useMediaGridAnchor } from '@/hooks/use-media-grid-anchor'
import type { MediaPage } from '@/lib/api.gen'
import { mediaGridLayout, mediaRowHeight, mediaRowIndex } from '@/lib/media-layout'

export type MediaGridHandle = { focusItem: (id: string) => Promise<boolean> }
type FocusRequest = { id: string; resolve: (focused: boolean) => void }

type MediaGridProps = {
  author: string
  page: MediaPage
  scroller: HTMLElement | null
  active: boolean
  listKey: string
  onOpen: (id: string) => void
  renderFavorite: (postId: string) => ReactNode
  ref?: Ref<MediaGridHandle>
}

/** Only nearby rows are mounted; a retained tab keeps its grid geometry. */
export function MediaGrid({
  author,
  page,
  scroller,
  active,
  listKey,
  onOpen,
  renderFavorite,
  ref,
}: MediaGridProps) {
  'use no memo'

  const grid = useRef<HTMLDivElement>(null)
  const width = useElementWidth(grid, { synchronous: true }) ?? 0
  const layout = useMemo(
    () => mediaGridLayout(page.items, page.missing, width),
    [page.items, page.missing, width],
  )
  const rowAt = useCallback(
    (index: number) => {
      const row = layout.rows[index]
      if (!row) throw new RangeError('Media grid row index is out of bounds')
      return row
    },
    [layout],
  )
  // A changed layout must remeasure section heights even when its row count stays equal.
  const getItemKey = useCallback(
    (index: number) => {
      const row = rowAt(index)
      return row.kind === 'tiles' ? row.key : row.kind
    },
    [rowAt],
  )
  const observeElementOffset = useMediaGridAnchor(layout, grid, scroller, listKey)
  // Virtualizer methods read mutable state; the component opts out of compiler memoization.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: layout.rows.length,
    getScrollElement: () => scroller,
    estimateSize: (index) => mediaRowHeight(rowAt(index), layout),
    getItemKey,
    observeElementOffset,
    overscan: 3,
  })

  const pendingFocus = useRef<FocusRequest | null>(null)
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null)
  useImperativeHandle(ref, () => ({
    focusItem(id) {
      pendingFocus.current?.resolve(false)
      pendingFocus.current = null
      setFocusRequest(null)
      if (!active || !scroller || mediaRowIndex(layout, id) < 0) return Promise.resolve(false)
      return new Promise<boolean>((resolve) => {
        const request = { id, resolve }
        pendingFocus.current = request
        setFocusRequest(request)
      })
    },
  }))
  useEffect(
    () => () => {
      pendingFocus.current?.resolve(false)
    },
    [],
  )
  useLayoutEffect(() => {
    if (!focusRequest || pendingFocus.current !== focusRequest) return
    const index = mediaRowIndex(layout, focusRequest.id)
    const finish = (focused: boolean): void => {
      focusRequest.resolve(focused)
      pendingFocus.current = null
      setFocusRequest(null)
    }
    if (!active || !scroller || index < 0) {
      finish(false)
      return
    }
    virtualizer.scrollToIndex(index, { align: 'auto', behavior: 'auto' })
    const button = [
      ...(grid.current?.querySelectorAll<HTMLButtonElement>('[data-media-id]') ?? []),
    ].find((element) => element.dataset.mediaId === focusRequest.id)
    if (button) {
      button.focus({ preventScroll: true })
      finish(document.activeElement === button)
      return
    }
  })

  return (
    <div
      ref={grid}
      data-media-grid=""
      inert={!active}
      className="relative w-full"
      style={{ height: virtualizer.getTotalSize() }}
    >
      {virtualizer.getVirtualItems().map((virtualRow) => {
        const row = rowAt(virtualRow.index)
        const transform = `translateY(${virtualRow.start}px)`
        if (row.kind !== 'tiles')
          return <MediaSection key={virtualRow.key} row={row} style={{ transform }} />
        return (
          <div
            key={virtualRow.key}
            className="absolute top-0 left-0 grid w-full"
            style={{
              transform,
              gridTemplateColumns: `repeat(${layout.columns}, minmax(0, 1fr))`,
              gap: layout.gap,
            }}
          >
            {row.items.map((item) => {
              const post = page.posts[item.post_id]
              if (!post) throw new Error(`Missing post metadata for media ${item.id}`)
              return (
                <MediaTile
                  key={item.id}
                  author={author}
                  item={item}
                  post={post}
                  active={active}
                  onOpen={onOpen}
                  favorite={renderFavorite(item.post_id)}
                />
              )
            })}
          </div>
        )
      })}
    </div>
  )
}
