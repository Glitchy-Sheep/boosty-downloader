import { expect, test } from 'vitest'

import { mediaListRowHeight, mediaListRowKey, mediaListRows } from '@/lib/media-list-layout'
import { playbackItem } from '@/test/playback-fixture'

test('list puts missing current files before the removed heading and keeps stable media keys', () => {
  const first = playbackItem()
  const last = playbackItem({ id: 'last', removed: true })
  const rows = mediaListRows([first, last], 2)
  expect(rows).toEqual([
    { kind: 'item', item: first },
    { kind: 'missing', count: 2, first: false },
    { kind: 'removed', count: 1, first: false },
    { kind: 'item', item: last },
  ])
  expect(rows.map(mediaListRowKey)).toEqual([
    `item:${first.id}`,
    'section:missing',
    'section:removed',
    `item:${last.id}`,
  ])
  expect(rows.map((row) => mediaListRowHeight(row, 64))).toEqual([64, 56, 92, 64])
})

test('opaque media identities cannot collide with virtual section keys', () => {
  const rows = mediaListRows(
    [playbackItem({ id: 'missing' }), playbackItem({ id: 'removed', removed: true })],
    1,
  )
  expect(new Set(rows.map(mediaListRowKey)).size).toBe(rows.length)
})

test('removed-only lists have no leading empty space and empty lists keep their missing note', () => {
  expect(mediaListRows([], 0)).toEqual([])
  const rows = mediaListRows([playbackItem({ removed: true })], 1)
  expect(rows.slice(0, 2)).toEqual([
    { kind: 'missing', count: 1, first: true },
    { kind: 'removed', count: 1, first: true },
  ])
  expect(rows.map((row) => mediaListRowHeight(row, 96))).toEqual([56, 68, 96])
})
