import { describe, expect, it } from 'vitest'

import type { PostRow } from '@/lib/api.gen'
import type { Order } from '@/lib/filters'
import { postNeighbours } from '@/lib/post-neighbours'

function row(id: string, created_at = '2026-11-01T00:00:00Z'): PostRow {
  return {
    id,
    created_at,
    title: id,
    access: 'open',
    counts: { audio: 0, files: 0, images: 0, videos: 0 },
    cover_path: null,
    favorite: false,
    match: null,
    missing_media: 0,
    seen: false,
    tier: null,
    updated: false,
  }
}

const older = row('a', '2026-10-01T00:00:00Z')
const current = row('m')
const newer = row('z', '2026-12-01T00:00:00Z')

describe('postNeighbours', () => {
  it.each<Order>(['newest', 'oldest'])('follows the actual filtered rows in %s order', (order) => {
    const first = order === 'oldest' ? older : newer
    const last = order === 'oldest' ? newer : older
    const rows = [first, current, last]
    expect(postNeighbours(rows, current, order)).toEqual({ previous: rows[0], next: rows[2] })
    expect(postNeighbours(rows, first, order)).toEqual({ previous: null, next: current })
    expect(postNeighbours(rows, last, order)).toEqual({ previous: current, next: null })
  })

  it.each<Order>(['newest', 'oldest'])(
    'places an excluded current post between dates in %s order',
    (order) => {
      const rows = order === 'oldest' ? [older, newer] : [newer, older]
      expect(postNeighbours(rows, current, order)).toEqual({ previous: rows[0], next: rows[1] })
    },
  )

  it.each<Order>(['newest', 'oldest'])('breaks equal timestamp ties by ID in %s order', (order) => {
    const before = row('a')
    const after = row('z')
    const rows = order === 'oldest' ? [before, after] : [after, before]
    expect(postNeighbours(rows, current, order)).toEqual({ previous: rows[0], next: rows[1] })
  })

  it.each<Order>(['newest', 'oldest'])(
    'handles excluded posts beyond either end in %s order',
    (order) => {
      const rows = order === 'oldest' ? [older, newer] : [newer, older]
      const earliest = row('before', '2026-01-01T00:00:00Z')
      const latest = row('after', '2027-01-01T00:00:00Z')
      const first = order === 'oldest' ? earliest : latest
      const last = order === 'oldest' ? latest : earliest
      expect(postNeighbours(rows, first, order)).toEqual({ previous: null, next: rows[0] })
      expect(postNeighbours(rows, last, order)).toEqual({ previous: rows[1], next: null })
    },
  )

  it.each<Order>(['newest', 'oldest'])(
    'matches SQLite Unicode ordering for tied IDs in %s order',
    (order) => {
      const before = row('\uE000')
      const selected = row('\u{10000}')
      const after = row('\u{10001}')
      const rows = order === 'oldest' ? [before, after] : [after, before]
      expect(postNeighbours(rows, selected, order)).toEqual({ previous: rows[0], next: rows[1] })
    },
  )

  it.each<Order>(['newest', 'oldest'])(
    'preserves microseconds before the ID tie-break in %s order',
    (order) => {
      const before = row('z', '2026-11-01T00:00:00.123100Z')
      const selected = row('m', '2026-11-01T03:00:00.123500+03:00')
      const after = row('a', '2026-11-01T00:00:00.123900Z')
      const rows = order === 'oldest' ? [before, after] : [after, before]
      expect(postNeighbours(rows, selected, order)).toEqual({ previous: rows[0], next: rows[1] })
    },
  )

  it('compares instants instead of raw offset strings', () => {
    const sameInstant = row('z', '2026-11-01T03:00:00+03:00')
    const earlier = row('x', '2026-11-01T01:00:00+03:00')
    expect(postNeighbours([sameInstant, earlier], current)).toEqual({
      previous: sameInstant,
      next: earlier,
    })
  })

  it('keeps the server order when an existing row has newer metadata than the detail', () => {
    const changed = { ...current, created_at: '2027-01-01T00:00:00Z' }
    expect(postNeighbours([changed, newer, older], current)).toEqual({
      previous: null,
      next: newer,
    })
  })

  it('returns no neighbours for empty results or the only result', () => {
    expect(postNeighbours([], current)).toEqual({ previous: null, next: null })
    expect(postNeighbours([current], current)).toEqual({ previous: null, next: null })
  })
})
