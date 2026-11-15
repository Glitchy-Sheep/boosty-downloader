import { observeElementOffset, type VirtualizerOptions } from '@tanstack/react-virtual'
import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from 'react'

import {
  mediaAnchorAt,
  mediaAnchorTop,
  type MediaGridAnchor,
  type MediaGridLayout,
} from '@/lib/media-layout'

type KeptGridPlace = { anchor: MediaGridAnchor | null; scrollTop: number }
type GridOffsetObserver = VirtualizerOptions<HTMLElement, Element>['observeElementOffset']
type GridOffsetListener = Parameters<GridOffsetObserver>[1]

/** Retain one anchor through a resize drag, until the reader scrolls again. */
export function useMediaGridAnchor(
  layout: MediaGridLayout,
  grid: RefObject<HTMLElement | null>,
  scroller: HTMLElement | null,
  listKey: string,
): GridOffsetObserver {
  const shown = useRef({ layout, listKey })
  // A shorter layout can clamp the live offset before the resize effect runs.
  const scrolled = useRef(0)
  const kept = useRef<KeptGridPlace | null>(null)
  const notifyOffset = useRef<GridOffsetListener | null>(null)
  const observeOffset = useCallback<GridOffsetObserver>((instance, notify) => {
    notifyOffset.current = notify
    const disconnect = observeElementOffset(instance, notify)
    return () => {
      notifyOffset.current = null
      disconnect?.()
    }
  }, [])
  useEffect(() => {
    if (!scroller) return
    const onScroll = (): void => {
      scrolled.current = scroller.scrollTop
    }
    onScroll()
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => scroller.removeEventListener('scroll', onScroll)
  }, [scroller])

  useLayoutEffect(() => {
    const previous = shown.current
    shown.current = { layout, listKey }
    if (!grid.current || !scroller) return
    if (previous.listKey !== listKey) {
      scroller.scrollTo({ top: 0, behavior: 'instant' })
      scrolled.current = scroller.scrollTop
      notifyOffset.current?.(scrolled.current, false)
      kept.current = null
      return
    }
    const last = previous.layout
    if (last.columns === layout.columns && last.tile === layout.tile) {
      if (last.rows !== layout.rows) kept.current = null
      return
    }
    const origin =
      grid.current.getBoundingClientRect().top -
      scroller.getBoundingClientRect().top +
      scroller.scrollTop
    const saved = kept.current
    const anchor =
      saved && Math.abs(scrolled.current - saved.scrollTop) <= 1
        ? saved.anchor
        : mediaAnchorAt(last, scrolled.current - origin)
    const top = anchor && mediaAnchorTop(layout, anchor)
    if (top !== null) scroller.scrollTo({ top: origin + top, behavior: 'instant' })
    scrolled.current = scroller.scrollTop
    // The restored viewport needs its rows before the browser sends a scroll event.
    notifyOffset.current?.(scrolled.current, false)
    kept.current = { anchor, scrollTop: scrolled.current }
  }, [layout, listKey, grid, scroller])
  return observeOffset
}
