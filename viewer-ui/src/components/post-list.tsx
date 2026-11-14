import { defaultRangeExtractor, useVirtualizer, type Range } from '@tanstack/react-virtual'
import { cn } from 'cn'
import { SearchX } from 'lucide-react'
import { useCallback, useLayoutEffect, useMemo, useRef, type CSSProperties } from 'react'

import { PostRow } from '@/components/post-row'
import type { PostRow as PostSummary } from '@/lib/api.gen'
import { rowMetrics } from '@/lib/sidebar'
import { buildTimeline, type MonthRow, type TimelineRow } from '@/lib/timeline'

const MONTH_HEIGHT = 32

type PostListProps = {
  author: string
  posts: PostSummary[] | undefined
  currentId: string | undefined
  listKey: string
  isStale: boolean
  width: number
  emptyMessage: string
  postHref: (id: string) => string
  onPost: (id: string) => void
}

/** A bounded timeline keeps only nearby posts and their active month mounted. */
export function PostList({ author, posts, currentId, listKey, isStale, width, emptyMessage, postHref, onPost }: PostListProps) {
  'use no memo'

  const scrollRef = useRef<HTMLDivElement>(null)
  const innerRef = useRef<HTMLDivElement>(null)
  const { rows, monthIndexes, rowIndexById } = useMemo(() => buildTimeline(posts ?? []), [posts])
  const stickyIndex = useRef(0)
  const metrics = useMemo(() => rowMetrics(width), [width])
  const sizeOf = useCallback((row: TimelineRow): number => {
    if (row.kind === 'month') return MONTH_HEIGHT
    return row.post.match?.text ? metrics.snippetHeight : metrics.height
  }, [metrics])
  const rangeExtractor = useCallback((range: Range): number[] => {
    stickyIndex.current = monthIndexes.findLast(index => index <= range.startIndex) ?? 0
    return [...new Set([stickyIndex.current, ...defaultRangeExtractor(range)])].sort((first, second) => first - second)
  }, [monthIndexes])
  const getItemKey = useCallback((index: number): string => `${rows[index].kind}:${rows[index].key}`, [rows])
  // Virtualizer methods read mutable state; this component opts out of compiler memoization.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: index => sizeOf(rows[index]),
    getItemKey,
    rangeExtractor,
    overscan: 8,
    scrollPaddingStart: MONTH_HEIGHT,
  })

  const shownMetrics = useRef(metrics)
  useLayoutEffect(() => {
    if (shownMetrics.current === metrics) return
    shownMetrics.current = metrics
    const top = (virtualizer.scrollOffset ?? 0) + MONTH_HEIGHT
    const anchor = virtualizer.getVirtualItems().find(item => item.end > top)
    virtualizer.measure()
    if (!anchor) return
    if (innerRef.current) innerRef.current.style.height = `${virtualizer.getTotalSize()}px`
    const moved = virtualizer.measurementsCache[anchor.index]
    if (!moved) return
    const inside = Math.min(top - anchor.start, moved.size - 1)
    virtualizer.scrollToOffset(moved.start + inside - MONTH_HEIGHT)
  }, [metrics, virtualizer])

  const shown = useRef<{ listKey: string; currentId?: string } | null>(null)
  const currentIndex = currentId === undefined ? undefined : rowIndexById.get(currentId)
  useLayoutEffect(() => {
    if (!posts?.length || isStale) return
    const previous = shown.current
    shown.current = { listKey, currentId }
    if (previous?.listKey !== listKey) {
      if (currentIndex === undefined) virtualizer.scrollToOffset(0)
      else virtualizer.scrollToIndex(currentIndex, { align: 'center' })
    } else if (previous.currentId !== currentId && currentIndex !== undefined) {
      virtualizer.scrollToIndex(currentIndex, { align: 'auto' })
    }
  })

  if (!posts) return <ListSkeleton />
  if (!posts.length) {
    return (
      <div role="status" className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-[13px] text-muted-foreground">
        <SearchX aria-hidden="true" className="size-5" />{emptyMessage}
      </div>
    )
  }

  const rowStyle = {
    '--cover-w': `${metrics.coverWidth}px`,
    '--row-gap': `${metrics.gap}px`,
    '--row-pad-x': `${metrics.padX}px`,
    '--title-size': `${metrics.titleSize}px`,
    '--title-leading': `${metrics.titleLeading}px`,
    '--title-lines': metrics.titleLines,
  } as CSSProperties

  return (
    <div
      ref={scrollRef}
      data-post-list=""
      aria-label="Post timeline"
      aria-busy={isStale}
      tabIndex={0}
      style={rowStyle}
      className={cn('min-h-0 flex-1 overflow-y-auto overscroll-contain outline-none transition-opacity duration-150 [overflow-anchor:none] focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset', isStale && 'opacity-60')}
    >
      <div ref={innerRef} className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map(item => {
          const row = rows[item.index]
          const pinned = item.index === stickyIndex.current
          return (
            <div key={item.key} className={pinned ? 'sticky top-0 z-10' : 'absolute top-0 left-0 w-full'} style={{ height: item.size, transform: pinned ? undefined : `translateY(${item.start}px)` }}>
              {row.kind === 'month'
                ? <MonthHeader row={row} />
                : <PostRow author={author} post={row.post} current={row.post.id === currentId} href={postHref(row.post.id)} onSelect={onPost} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MonthHeader({ row }: { row: MonthRow }) {
  return (
    <h2 data-month={row.key} className="flex h-full items-end justify-between border-b bg-card/90 px-(--row-pad-x) pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase backdrop-blur-md">
      <span>{row.label}</span><span className="font-medium tracking-normal tabular-nums">{row.count}</span>
    </h2>
  )
}

function ListSkeleton() {
  return (
    <div role="status" aria-label="Loading posts" className="relative flex-1 overflow-hidden">
      <span className="sr-only">Loading posts...</span>
      {Array.from({ length: 9 }, (_, index) => (
        <div key={index} aria-hidden="true" className="flex gap-3 px-4 py-[11px]">
          <div className="h-[54px] w-[96px] rounded-[6px] bg-muted motion-safe:animate-pulse" />
          <div className="flex flex-1 flex-col gap-2 pt-1">
            <div className="h-3.5 w-11/12 rounded bg-muted" />
            <div className="h-3.5 w-2/3 rounded bg-muted" />
            <div className="mt-auto h-3 w-1/3 rounded bg-muted" />
          </div>
        </div>
      ))}
    </div>
  )
}
