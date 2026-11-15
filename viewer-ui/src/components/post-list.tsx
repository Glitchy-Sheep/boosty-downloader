import {
  defaultRangeExtractor,
  observeElementOffset,
  useVirtualizer,
  type Range,
  type VirtualizerOptions,
} from '@tanstack/react-virtual'
import { cn } from 'cn'
import { SearchX } from 'lucide-react'
import {
  useCallback,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react'
import { flushSync } from 'react-dom'

import { MonthScrubber } from '@/components/month-scrubber'
import { PostRow, type PostRowProps } from '@/components/post-row'
import { useFavorite } from '@/hooks/use-favorite'
import type { PostRow as PostSummary } from '@/lib/api.gen'
import { rowMetrics, type RowMetrics } from '@/lib/sidebar'
import { buildTimeline, type MonthRow, type TimelineRow } from '@/lib/timeline'
import {
  timelineAnchorAt,
  timelineAnchorOffset,
  timelineExtent,
  type TimelineAnchor,
} from '@/lib/timeline-anchor'

const MONTH_HEIGHT = 32

type PostListProps = {
  author: string
  posts: PostSummary[] | undefined
  currentId: string | undefined
  listKey: string
  isStale: boolean
  navigationDisabled: boolean
  width: number
  emptyMessage: string
  postHref: (id: string) => string
  onPost: (id: string) => void
}

type ShownSelection = { listKey: string; currentId: string | undefined }
type AppliedTimeline = { width: number; height: number; metrics: RowMetrics; rows: TimelineRow[] }
type TimelineOffsetObserver = VirtualizerOptions<HTMLDivElement, Element>['observeElementOffset']
type TimelineOffsetListener = Parameters<TimelineOffsetObserver>[1]

/** A bounded timeline keeps only nearby posts and their active month mounted. */
export function PostList({
  author,
  posts,
  currentId,
  listKey,
  isStale,
  navigationDisabled,
  width,
  emptyMessage,
  postHref,
  onPost,
}: PostListProps) {
  'use no memo'

  const scrollRef = useRef<HTMLDivElement>(null)
  const innerRef = useRef<HTMLDivElement>(null)
  const [minimumOffset, setMinimumOffset] = useState(0)
  const applied = useRef<AppliedTimeline | null>(null)
  const keptAnchor = useRef<TimelineAnchor | null>(null)
  const restoredOffset = useRef<number | null>(null)
  const restoring = useRef(false)
  const notifyOffset = useRef<TimelineOffsetListener | null>(null)
  const { rows, monthIndexes, monthTargets, rowIndexById } = useMemo(
    () => buildTimeline(posts ?? []),
    [posts],
  )
  const stickyIndex = useRef(0)
  const metrics = useMemo(() => rowMetrics(width), [width])
  const sizeOf = useCallback(
    (row: TimelineRow): number => {
      if (row.kind === 'month') return MONTH_HEIGHT
      return row.post.match?.text ? metrics.snippetHeight : metrics.height
    },
    [metrics],
  )
  const rangeExtractor = useCallback(
    (range: Range): number[] => {
      stickyIndex.current = monthIndexes.findLast((index) => index <= range.startIndex) ?? 0
      return [...new Set([stickyIndex.current, ...defaultRangeExtractor(range)])].sort(
        (first, second) => first - second,
      )
    },
    [monthIndexes],
  )
  const rowAt = useCallback(
    (index: number): TimelineRow => {
      const row = rows[index]
      if (!row) throw new RangeError('Timeline row index is out of bounds')
      return row
    },
    [rows],
  )
  const getItemKey = useCallback(
    (index: number): string => {
      const row = rowAt(index)
      return `${row.kind}:${row.key}`
    },
    [rowAt],
  )
  const observeOffset = useCallback<TimelineOffsetObserver>((instance, notify) => {
    notifyOffset.current = notify
    const disconnect = observeElementOffset(instance, (offset, scrolling) => {
      const element = instance.scrollElement
      const previous = applied.current
      const isRestoredOffset =
        restoredOffset.current !== null && Math.abs(offset - restoredOffset.current) <= 1
      const sameGeometry =
        element &&
        previous &&
        element.offsetWidth === previous.width &&
        element.clientHeight === previous.height
      const readerScroll = !restoring.current && !isRestoredOffset && sameGeometry
      // Native clamping during reflow must not replace the last stable row anchor.
      if (readerScroll) {
        keptAnchor.current = timelineAnchorAt(instance.measurementsCache, offset, MONTH_HEIGHT)
        restoredOffset.current = null
        setMinimumOffset(offset)
      }
      notify(offset, Boolean(scrolling && readerScroll))
    })
    return () => {
      notifyOffset.current = null
      disconnect?.()
    }
  }, [])
  // Virtualizer methods read mutable state; this component opts out of compiler memoization.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => sizeOf(rowAt(index)),
    getItemKey,
    rangeExtractor,
    overscan: 8,
    scrollPaddingStart: MONTH_HEIGHT,
    observeElementOffset: observeOffset,
  })

  const restoreGeometry = useEffectEvent(() => {
    const element = scrollRef.current
    const inner = innerRef.current
    if (!element || !inner || element.offsetWidth !== width || element.clientHeight <= 0) return
    const previous = applied.current
    const geometry = { width, height: element.clientHeight, metrics, rows }
    if (
      previous?.width === width &&
      previous.height === geometry.height &&
      previous.metrics === metrics &&
      previous.rows === rows
    )
      return
    const anchor =
      keptAnchor.current ??
      timelineAnchorAt(virtualizer.measurementsCache, element.scrollTop, MONTH_HEIGHT)
    restoring.current = true
    virtualizer.measure()
    const logicalHeight = virtualizer.getTotalSize()
    const target =
      anchor && timelineAnchorOffset(anchor, virtualizer.measurementsCache, MONTH_HEIGHT)
    const lastOffset = Math.max(0, logicalHeight - geometry.height)
    const offset = target ?? Math.min(element.scrollTop, lastOffset)
    const extent = timelineExtent(logicalHeight, offset)
    inner.style.height = extent.height
    inner.style.minHeight = `${extent.minHeight}px`
    setMinimumOffset(offset)
    applied.current = geometry
    virtualizer.scrollToOffset(offset)
    restoredOffset.current = element.scrollTop
    keptAnchor.current =
      target === null
        ? timelineAnchorAt(virtualizer.measurementsCache, element.scrollTop, MONTH_HEIGHT)
        : anchor
    // The restored viewport needs its virtual rows before the browser's scroll event.
    notifyOffset.current?.(element.scrollTop, false)
    restoring.current = false
  })
  useLayoutEffect(() => restoreGeometry())
  const hasPosts = Boolean(posts?.length)
  useLayoutEffect(() => {
    const element = scrollRef.current
    if (!element) return
    const observer = new ResizeObserver(() => flushSync(() => restoreGeometry()))
    observer.observe(element)
    return () => observer.disconnect()
  }, [hasPosts])

  const navigateTimeline = (move: () => void): void => {
    restoring.current = true
    setMinimumOffset(0)
    if (innerRef.current) {
      const extent = timelineExtent(virtualizer.getTotalSize(), 0)
      innerRef.current.style.height = extent.height
      innerRef.current.style.minHeight = `${extent.minHeight}px`
    }
    move()
    const offset = scrollRef.current?.scrollTop ?? 0
    keptAnchor.current = timelineAnchorAt(virtualizer.measurementsCache, offset, MONTH_HEIGHT)
    restoredOffset.current = offset
    setMinimumOffset(offset)
    notifyOffset.current?.(offset, false)
    restoring.current = false
  }

  const shown = useRef<ShownSelection | null>(null)
  const currentIndex = currentId === undefined ? undefined : rowIndexById.get(currentId)
  useLayoutEffect(() => {
    if (!posts?.length || isStale) return
    const previous = shown.current
    shown.current = { listKey, currentId }
    if (previous?.listKey !== listKey) {
      navigateTimeline(() => {
        if (currentIndex === undefined) virtualizer.scrollToOffset(0)
        else virtualizer.scrollToIndex(currentIndex, { align: 'center' })
      })
    } else if (previous.currentId !== currentId && currentIndex !== undefined) {
      navigateTimeline(() => virtualizer.scrollToIndex(currentIndex, { align: 'auto' }))
    }
  })

  if (!posts) return <ListSkeleton />
  if (!posts.length) {
    return (
      <div
        role="status"
        className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-[13px] text-muted-foreground"
      >
        <SearchX aria-hidden="true" className="size-5" />
        {emptyMessage}
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

  const virtualItems = virtualizer.getVirtualItems()
  const activeMonth = rows[stickyIndex.current]
  const currentMonth = activeMonth?.kind === 'month' ? activeMonth.key : undefined

  return (
    <>
      <MonthScrubber
        months={monthTargets}
        currentKey={currentMonth}
        disabled={navigationDisabled}
        onMonth={(target) => {
          if (navigationDisabled) return
          navigateTimeline(() =>
            virtualizer.scrollToIndex(target.firstPostIndex, { align: 'start' }),
          )
        }}
      />
      <div
        ref={scrollRef}
        data-post-list=""
        aria-label="Post timeline"
        aria-busy={isStale}
        // Keyboard focus lets users scroll the timeline without selecting a post.
        // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        style={rowStyle}
        className={cn(
          'min-h-0 flex-1 overflow-y-auto overscroll-contain outline-none transition-opacity duration-150 [overflow-anchor:none] focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset',
          isStale && 'opacity-60',
        )}
      >
        <div
          ref={innerRef}
          className="relative w-full"
          style={timelineExtent(virtualizer.getTotalSize(), minimumOffset)}
        >
          {virtualItems.map((item) => {
            const row = rowAt(item.index)
            const pinned = item.index === stickyIndex.current
            return (
              <div
                key={item.key}
                className={pinned ? 'sticky top-0 z-10' : 'absolute top-0 left-0 w-full'}
                style={{
                  height: item.size,
                  transform: pinned ? undefined : `translateY(${item.start}px)`,
                }}
              >
                {row.kind === 'month' ? (
                  <MonthHeader row={row} />
                ) : (
                  <MarkedPostRow
                    author={author}
                    post={row.post}
                    current={row.post.id === currentId}
                    href={postHref(row.post.id)}
                    onSelect={onPost}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}

type MarkedPostRowProps = Omit<PostRowProps, 'favorite'>

function MarkedPostRow(props: MarkedPostRowProps) {
  const favorite = useFavorite(props.author, props.post.id)
  return <PostRow {...props} favorite={favorite} />
}

function MonthHeader({ row }: { row: MonthRow }) {
  return (
    <h2
      data-month={row.key}
      className="flex h-full items-end justify-between border-b bg-card/90 px-(--row-pad-x) pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase backdrop-blur-md"
    >
      <span>{row.label}</span>
      <span className="font-medium tracking-normal tabular-nums">{row.count}</span>
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
