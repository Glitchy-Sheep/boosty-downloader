import { expect, test } from 'vitest'

import { countMarkChanges, isPostUnread, nextSeenMark, postMarkChange } from '@/lib/post-marks'
import { savedRow } from '@/test/post-fixtures'

test.each([
  { seen: false, updated: false, unread: true },
  { seen: true, updated: false, unread: false },
  { seen: true, updated: true, unread: true },
])('uses current content rather than historical seen=$seen, updated=$updated', (state) => {
  const row = { ...savedRow, seen: state.seen, updated: state.updated }
  expect(isPostUnread(row)).toBe(state.unread)
  expect(nextSeenMark(row)).toBe(state.unread)
  expect(postMarkChange(row, 'seen')).toEqual({
    kind: 'seen',
    previous: { seen: state.seen, updated: state.updated },
    next: { seen: state.unread, updated: false },
  })
})

test('counts actual seen changes, excluding locked and already matching posts', () => {
  const rows = [
    { ...savedRow, id: 'new', seen: false },
    { ...savedRow, id: 'seen', seen: true },
    { ...savedRow, id: 'updated', seen: true, updated: true },
    { ...savedRow, id: 'locked', seen: false, access: 'locked' as const },
    { ...savedRow, id: 'locked-saved', seen: true, updated: true, access: 'locked' as const },
  ]
  expect(countMarkChanges(rows, true)).toBe(2)
  expect(countMarkChanges(rows, false)).toBe(2)
  expect(countMarkChanges([], true)).toBe(0)
  expect(isPostUnread({ ...savedRow, access: 'locked' })).toBe(false)
})

test('favorite transitions own only the favorite value', () => {
  expect(postMarkChange(savedRow, 'favorite')).toEqual({
    kind: 'favorite',
    previous: true,
    next: false,
  })
})
