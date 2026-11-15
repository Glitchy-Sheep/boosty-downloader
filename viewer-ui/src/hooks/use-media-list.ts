import { useVirtualizer } from '@tanstack/react-virtual'
import { useCallback, useLayoutEffect, useMemo } from 'react'

import type { MediaPage } from '@/lib/api.gen'
import { mediaListRowHeight, mediaListRowKey, mediaListRows } from '@/lib/media-list-layout'

export type MediaListProps = {
  author: string
  page: MediaPage
  scroller: HTMLElement | null
  active: boolean
  listKey: string
}

export function useMediaList({ page, scroller, listKey }: MediaListProps, height: number) {
  'use no memo'
  const rows = useMemo(() => mediaListRows(page.items, page.missing), [page.items, page.missing])
  const rowAt = useCallback(
    (index: number) => {
      const row = rows[index]
      if (!row) throw new RangeError('Media list row index is out of bounds')
      return row
    },
    [rows],
  )
  const getItemKey = useCallback((index: number) => mediaListRowKey(rowAt(index)), [rowAt])
  // Virtualizer methods read mutable state; this hook opts out of compiler memoization.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller,
    estimateSize: (index) => mediaListRowHeight(rowAt(index), height),
    getItemKey,
    overscan: 6,
  })
  useLayoutEffect(() => {
    if (scroller) scroller.scrollTop = 0
  }, [scroller, listKey])
  return {
    height: virtualizer.getTotalSize(),
    rows: virtualizer
      .getVirtualItems()
      .map((row) => ({ key: row.key, start: row.start, row: rowAt(row.index) })),
  }
}
