import { expect, test } from 'vitest'

import {
  mediaAnchorAt,
  mediaAnchorTop,
  mediaGridLayout,
  mediaGridRows,
  mediaRowHeight,
  mediaRowIndex,
  mediaSectionHeight,
  type MediaGridAnchor,
} from '@/lib/media-layout'
import { savedVideo } from '@/test/post-fixtures'

const photos = Array.from({ length: 2000 }, (_, index) => ({
  ...savedVideo,
  id: `photo-${index}`,
  kind: 'images' as const,
}))

test('groups square tiles between three and eight columns without reordering server items', () => {
  for (const width of [0, 280, 390, 640, 920, 1400, 2000]) {
    const layout = mediaGridLayout(photos, 0, width)
    expect(layout.columns).toBeGreaterThanOrEqual(3)
    expect(layout.columns).toBeLessThanOrEqual(8)
    expect(layout.rows.flatMap((row) => (row.kind === 'tiles' ? row.items : []))).toEqual(photos)
    if (width)
      expect(layout.tile * layout.columns + layout.gap * (layout.columns - 1)).toBeCloseTo(width)
    else expect(layout.tile).toBe(190)
  }
  expect(mediaGridLayout(photos, 0, 2000).columns).toBe(8)
})

test('puts the missing note before retained removed copies and keeps their order', () => {
  const current = photos.slice(0, 4)
  const removed = photos.slice(4, 9).map((item) => ({ ...item, removed: true }))
  const rows = mediaGridRows([...current, ...removed], 3, 7)
  expect(rows.map((row) => row.kind)).toEqual([
    'tiles',
    'tiles',
    'missing',
    'removed',
    'tiles',
    'tiles',
  ])
  expect(rows[2]).toEqual({ kind: 'missing', count: 7, first: false })
  expect(rows[3]).toEqual({ kind: 'removed', count: 5, first: false })
  expect(new Set(rows.map((row) => (row.kind === 'tiles' ? row.key : row.kind))).size).toBe(
    rows.length,
  )
  expect(mediaSectionHeight({ kind: 'missing', count: 7, first: false })).toBe(56)
  expect(mediaSectionHeight({ kind: 'removed', count: 5, first: false })).toBe(92)
})

test('removed-only and empty selections have no leading divider space', () => {
  const rows = mediaGridRows(
    photos.slice(0, 2).map((item) => ({ ...item, removed: true })),
    3,
    0,
  )
  expect(rows[0]).toEqual({ kind: 'removed', count: 2, first: true })
  expect(mediaSectionHeight({ kind: 'removed', count: 2, first: true })).toBe(68)
  expect(mediaGridRows([], 3, 0)).toEqual([])
  expect(mediaGridRows([], 3, 1)).toEqual([{ kind: 'missing', count: 1, first: true }])
})

test('retains the original top tile and partial row through every width of a continuous drag', () => {
  const initial = mediaGridLayout(photos, 0, 1400)
  const anchor = mediaAnchorAt(initial, 12_345)
  expect(anchor?.kind).toBe('tiles')
  if (!anchor || anchor.kind !== 'tiles') throw new Error('Expected the middle photo')
  const widths = [1200, 970, 840, 720, 530, 390, 280, 410, 780, 950, 1100, 1400]
  for (const width of widths) {
    const layout = mediaGridLayout(photos, 0, width)
    const offset = mediaAnchorTop(layout, anchor)
    expect(offset).not.toBeNull()
    const current = mediaAnchorAt(layout, offset ?? 0)
    expect(current?.fraction).toBeCloseTo(anchor.fraction)
    const row = layout.rows[mediaRowIndex(layout, anchor.id)]
    expect(row?.kind === 'tiles' && row.items.some((item) => item.id === anchor.id)).toBe(true)
    expect(current?.kind === 'tiles' && mediaRowIndex(layout, current.id)).toBe(
      mediaRowIndex(layout, anchor.id),
    )
  }
})

test('anchors section rows and ignores off-grid offsets and disappeared pieces', () => {
  const items = photos
    .slice(0, 3)
    .concat(photos.slice(3, 6).map((item) => ({ ...item, removed: true })))
  const layout = mediaGridLayout(items, 2, 570)
  const first = layout.rows[0]
  if (!first) throw new Error('Expected a tile row')
  const tileHeight = mediaRowHeight(first, layout)
  const missing: MediaGridAnchor = { kind: 'missing', fraction: 0.5 }
  const removed: MediaGridAnchor = { kind: 'removed', fraction: 0.25 }
  expect(mediaAnchorAt(layout, tileHeight + 28)).toEqual(missing)
  expect(mediaAnchorTop(layout, missing)).toBe(tileHeight + 28)
  expect(mediaAnchorAt(layout, tileHeight + 56 + 23)?.kind).toBe('removed')
  expect(mediaAnchorAt(layout, tileHeight + 56 + 23)?.fraction).toBeCloseTo(removed.fraction)
  expect(mediaAnchorTop(layout, removed)).toBe(tileHeight + 56 + 23)
  expect(mediaAnchorAt(layout, tileHeight - 0.5)).toEqual({ kind: 'missing', fraction: 0 })
  expect(mediaAnchorAt(layout, 0)).toBeNull()
  expect(mediaAnchorAt(layout, -10)).toBeNull()
  expect(mediaAnchorAt(layout, 100_000)).toBeNull()
  expect(mediaAnchorTop(layout, { kind: 'tiles', id: 'gone', fraction: 0 })).toBeNull()
  expect(mediaAnchorTop(mediaGridLayout([], 0, 570), missing)).toBeNull()
  expect(mediaRowIndex(layout, 'gone')).toBe(-1)
})
