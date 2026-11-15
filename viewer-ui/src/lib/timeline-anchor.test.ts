import { expect, test } from 'vitest'

import {
  timelineAnchorAt,
  timelineAnchorOffset,
  type TimelineMeasurement,
} from '@/lib/timeline-anchor'

function measurements(size: number, count = 10): TimelineMeasurement[] {
  return Array.from({ length: count }, (_, index) => ({
    key: `post:${index}`,
    index,
    start: 32 + index * size,
    end: 32 + (index + 1) * size,
    size,
  }))
}

test('keeps the first unobscured row and its inside offset across width changes', () => {
  const anchor = timelineAnchorAt(measurements(100), 245, 32)
  expect(anchor).toEqual({ key: 'post:2', index: 2, inside: 45 })
  expect(anchor && timelineAnchorOffset(anchor, measurements(120), 32)).toBe(285)
})

test('clamps an inside offset only when the anchored row becomes shorter', () => {
  const anchor = timelineAnchorAt(measurements(100), 299, 32)
  expect(anchor && timelineAnchorOffset(anchor, measurements(80), 32)).toBe(239)
  expect(anchor && timelineAnchorOffset(anchor, measurements(100), 32)).toBe(299)
})

test('finds a moved keyed row without trusting its previous index', () => {
  const anchor = timelineAnchorAt(measurements(100), 245, 32)
  const reordered = measurements(100).map((row) => ({
    ...row,
    key: row.key === 'post:2' ? 'post:4' : row.key,
  }))
  reordered[4] = { key: 'post:2', index: 4, start: 432, end: 532, size: 100 }
  expect(anchor && timelineAnchorOffset(anchor, reordered, 32)).toBe(445)
  expect(anchor && timelineAnchorOffset(anchor, [], 32)).toBeNull()
})

test('handles an empty timeline, exact row boundaries and the end', () => {
  expect(timelineAnchorAt([], 0, 32)).toBeNull()
  expect(timelineAnchorAt(measurements(100), 100, 32)?.key).toBe('post:1')
  expect(timelineAnchorAt(measurements(100), 1000, 32)).toBeNull()
  const start = timelineAnchorAt(measurements(100), 0, 32)
  expect(start && timelineAnchorOffset(start, measurements(100), 64)).toBe(0)
})
