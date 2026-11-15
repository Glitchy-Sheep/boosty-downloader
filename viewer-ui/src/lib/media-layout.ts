import type { MediaItem } from '@/lib/api.gen'

export type MediaSectionRow = {
  kind: 'missing' | 'removed'
  count: number
  first: boolean
}
export type MediaTileRow = { kind: 'tiles'; items: readonly MediaItem[]; key: string }
export type MediaGridRow = MediaTileRow | MediaSectionRow
export type MediaGridLayout = {
  rows: readonly MediaGridRow[]
  columns: number
  tile: number
  gap: number
}
export type MediaGridAnchor =
  | { kind: 'tiles'; id: string; fraction: number }
  | { kind: 'missing' | 'removed'; fraction: number }

const TILE_TARGET = 190
const MIN_COLUMNS = 3
const MAX_COLUMNS = 8

function tileRows(items: readonly MediaItem[], columns: number, section: string): MediaTileRow[] {
  return Array.from({ length: Math.ceil(items.length / columns) }, (_, index) => ({
    kind: 'tiles',
    items: items.slice(index * columns, (index + 1) * columns),
    key: `${section}:${index}`,
  }))
}

/** Missing current media precede the retained copies removed from their posts. */
export function mediaGridRows(
  items: readonly MediaItem[],
  columns: number,
  missing: number,
): MediaGridRow[] {
  const firstRemoved = items.findIndex((item) => item.removed)
  const split = firstRemoved < 0 ? items.length : firstRemoved
  const rows: MediaGridRow[] = tileRows(items.slice(0, split), columns, 'current')
  if (missing > 0) rows.push({ kind: 'missing', count: missing, first: split === 0 })
  if (split < items.length)
    rows.push({ kind: 'removed', count: items.length - split, first: split === 0 })
  return [...rows, ...tileRows(items.slice(split), columns, 'removed')]
}

export function mediaSectionHeight(row: MediaSectionRow): number {
  switch (row.kind) {
    case 'missing':
      return 56
    case 'removed':
      return row.first ? 68 : 92
  }
}

export function mediaRowHeight(row: MediaGridRow, layout: MediaGridLayout): number {
  if (row.kind === 'tiles') return layout.tile + layout.gap
  return mediaSectionHeight(row)
}

export function mediaGridLayout(
  items: readonly MediaItem[],
  missing: number,
  width: number,
): MediaGridLayout {
  const columns = Math.min(MAX_COLUMNS, Math.max(MIN_COLUMNS, Math.round(width / TILE_TARGET)))
  const gap = width < 640 ? 2 : 4
  const tile = width > 0 ? Math.max(1, (width - gap * (columns - 1)) / columns) : TILE_TARGET
  return { rows: mediaGridRows(items, columns, missing), columns, tile, gap }
}

/** Anchor the first row with a whole visible pixel, keeping its hidden fraction. */
export function mediaAnchorAt(layout: MediaGridLayout, top: number): MediaGridAnchor | null {
  if (top <= 0) return null
  let start = 0
  for (const row of layout.rows) {
    const height = mediaRowHeight(row, layout)
    if (start + height > top + 1) {
      const fraction = Math.max(0, (top - start) / height)
      if (row.kind !== 'tiles') return { kind: row.kind, fraction }
      const first = row.items[0]
      return first ? { kind: 'tiles', id: first.id, fraction } : null
    }
    start += height
  }
  return null
}

export function mediaAnchorTop(layout: MediaGridLayout, anchor: MediaGridAnchor): number | null {
  let top = 0
  for (const row of layout.rows) {
    const height = mediaRowHeight(row, layout)
    const matches =
      anchor.kind === 'tiles'
        ? row.kind === 'tiles' && row.items.some((item) => item.id === anchor.id)
        : row.kind === anchor.kind
    if (matches) return top + anchor.fraction * height
    top += height
  }
  return null
}

export function mediaRowIndex(layout: MediaGridLayout, id: string): number {
  return layout.rows.findIndex(
    (row) => row.kind === 'tiles' && row.items.some((item) => item.id === id),
  )
}
