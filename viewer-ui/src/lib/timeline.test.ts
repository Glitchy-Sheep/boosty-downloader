import { describe, expect, it } from 'vitest'

import type { PostRow } from '@/lib/api.gen'
import { buildTimeline } from '@/lib/timeline'

function post(id: string, created_at: string): PostRow {
  return {
    id,
    created_at,
    title: id,
    access: 'open',
    counts: { images: 0, videos: 0, audio: 0, files: 0 },
    cover_path: null,
    favorite: false,
    match: null,
    missing_media: 0,
    seen: false,
    tier: null,
    updated: false,
  }
}

describe('author timeline', () => {
  it('handles an empty filtered list', () => {
    expect(buildTimeline([])).toEqual({
      rows: [],
      monthIndexes: [],
      monthTargets: [],
      rowIndexById: new Map(),
    })
  })

  it('groups newest-first posts and maps selected IDs to virtual rows', () => {
    const posts = [
      post('new', '2026-03-20T00:00:00Z'),
      post('same-month', '2026-03-01T00:00:00Z'),
      post('old', '2025-12-31T00:00:00Z'),
    ]
    const timeline = buildTimeline(posts)
    expect(timeline.monthIndexes).toEqual([0, 3])
    expect(timeline.rows[0]).toEqual({
      kind: 'month',
      key: '2026-03',
      label: 'March 2026',
      year: '2026',
      count: 2,
      firstPostIndex: 1,
    })
    expect(timeline.rows[3]).toEqual({
      kind: 'month',
      key: '2025-12',
      label: 'December 2025',
      year: '2025',
      count: 1,
      firstPostIndex: 4,
    })
    expect(timeline.rowIndexById.get('new')).toBe(1)
    expect(timeline.rowIndexById.get('same-month')).toBe(2)
    expect(timeline.rowIndexById.get('old')).toBe(4)
    expect(timeline.rowIndexById.get('excluded')).toBeUndefined()
    expect(timeline.rows[2]).toEqual({ kind: 'post', key: 'same-month', post: posts[1] })
  })

  it('keeps oldest-first and same-timestamp server ordering without mutating rows', () => {
    const posts = [
      post('old', '2025-12-31T00:00:00Z'),
      post('second', '2026-03-01T00:00:00Z'),
      post('first', '2026-03-01T00:00:00Z'),
    ]
    const before = structuredClone(posts)
    const timeline = buildTimeline(Object.freeze(posts))
    expect(timeline.rows.filter((row) => row.kind === 'post').map((row) => row.post.id)).toEqual([
      'old',
      'second',
      'first',
    ])
    expect(timeline.monthIndexes).toEqual([0, 2])
    expect(timeline.rows[2]).toMatchObject({ key: '2026-03', count: 2 })
    expect(posts).toEqual(before)
  })

  it('groups offset timestamps by UTC and keeps all access and search data intact', () => {
    const newer = post('next', '2026-01-01T00:30:00Z')
    const locked = {
      ...post('locked', '2026-01-01T00:30:00+03:00'),
      access: 'locked' as const,
      tier: 'Gold',
      match: { title: [{ text: '<script>', matched: true }], text: null },
    }
    const timeline = buildTimeline([newer, locked])
    expect(timeline.rows[0]).toMatchObject({ key: '2026-01', count: 1 })
    expect(timeline.rows[2]).toMatchObject({ key: '2025-12', count: 1 })
    const row = timeline.rows[3]
    expect(row?.kind).toBe('post')
    if (row?.kind === 'post') expect(row.post).toBe(locked)
  })

  it.each(['newest', 'oldest'])(
    'targets the first post of every sparse month in %s order',
    (order) => {
      const posts = [
        post('latest', '2026-11-01T00:00:00Z'),
        post('march-end', '2021-03-31T20:00:00Z'),
        post('march-start', '2021-03-01T00:00:00Z'),
        post('earliest', '2019-01-01T00:00:00Z'),
      ]
      if (order === 'oldest') posts.reverse()
      const timeline = buildTimeline(posts)
      const targets = timeline.monthTargets
      expect(targets.map(({ key }) => key)).toEqual(
        order === 'newest' ? ['2026-11', '2021-03', '2019-01'] : ['2019-01', '2021-03', '2026-11'],
      )
      expect(targets.map(({ count }) => count)).toEqual([1, 2, 1])
      expect(targets.map(({ firstPostIndex }) => firstPostIndex)).toEqual([1, 3, 6])
      for (const target of targets) {
        const firstPost = timeline.rows[target.firstPostIndex]
        expect(firstPost?.kind).toBe('post')
        if (firstPost?.kind === 'post') {
          expect(firstPost.post.created_at.slice(0, 7)).toBe(target.key)
        }
        expect(timeline.rows[target.firstPostIndex - 1]).toBe(target)
      }
    },
  )

  it('replaces target counts and offsets for a filtered list without retaining excluded months', () => {
    const posts = [
      post('latest', '2026-11-01T00:00:00Z'),
      post('march-end', '2021-03-31T20:00:00Z'),
      post('march-start', '2021-03-01T00:00:00Z'),
      post('earliest', '2019-01-01T00:00:00Z'),
    ]
    const full = buildTimeline(posts)
    const filtered = buildTimeline(posts.filter(({ id }) => id === 'march-start'))
    expect(filtered.monthTargets).toEqual([
      {
        kind: 'month',
        key: '2021-03',
        label: 'March 2021',
        year: '2021',
        count: 1,
        firstPostIndex: 1,
      },
    ])
    expect(full.monthTargets.find(({ key }) => key === '2021-03')).toMatchObject({
      count: 2,
      firstPostIndex: 3,
    })
  })

  it('uses the UTC year for navigation across a local year boundary', () => {
    const { monthTargets } = buildTimeline([
      post('offset', '2021-01-01T00:30:00+03:00'),
      post('utc', '2020-12-01T00:00:00Z'),
    ])
    expect(monthTargets).toHaveLength(1)
    expect(monthTargets[0]).toMatchObject({
      key: '2020-12',
      label: 'December 2020',
      year: '2020',
      count: 2,
      firstPostIndex: 1,
    })
  })
})
