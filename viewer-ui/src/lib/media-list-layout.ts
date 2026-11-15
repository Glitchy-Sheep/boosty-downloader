import type { MediaItem } from '@/lib/api.gen'
import { mediaGridRows, mediaSectionHeight, type MediaSectionRow } from '@/lib/media-layout'

export type MediaListRow = { kind: 'item'; item: MediaItem } | MediaSectionRow

/** Single-piece rows share the grid's current, missing and removed section order. */
export function mediaListRows(items: readonly MediaItem[], missing: number): MediaListRow[] {
  return mediaGridRows(items, 1, missing).flatMap((row): MediaListRow[] => {
    if (row.kind !== 'tiles') return [row]
    return row.items.map((item) => ({ kind: 'item', item }))
  })
}

export function mediaListRowHeight(row: MediaListRow, height: number): number {
  return row.kind === 'item' ? height : mediaSectionHeight(row)
}

export function mediaListRowKey(row: MediaListRow): string {
  return row.kind === 'item' ? `item:${row.item.id}` : `section:${row.kind}`
}
