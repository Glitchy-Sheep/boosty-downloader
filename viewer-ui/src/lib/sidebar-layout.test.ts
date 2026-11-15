import { afterEach, expect, test, vi } from 'vitest'

import {
  clampSidebarWidth,
  loadSidebarLayout,
  saveSidebarLayout,
  SIDEBAR_STORAGE_KEY,
} from '@/lib/sidebar-layout'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

test('defaults to an open 360px sidebar when no preference exists', () => {
  expect(loadSidebarLayout()).toEqual({ width: 360, collapsed: false })
})

test.each([
  'invalid json',
  'null',
  '[]',
  'false',
  '42',
  '{}',
  '{"width":420}',
  '{"collapsed":true}',
  '{"width":"420","collapsed":true}',
  '{"width":1e999,"collapsed":true}',
  '{"width":420,"collapsed":"true"}',
])('rejects malformed persisted layout %s', (stored) => {
  localStorage.setItem(SIDEBAR_STORAGE_KEY, stored)
  expect(loadSidebarLayout()).toEqual({ width: 360, collapsed: false })
})

test.each([
  { stored: -10, expected: 260 },
  { stored: 260, expected: 260 },
  { stored: 487.5, expected: 487.5 },
  { stored: 640, expected: 640 },
  { stored: 900, expected: 640 },
])('bounds a valid saved width of $stored to $expected', ({ stored, expected }) => {
  localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify({ width: stored, collapsed: true }))
  expect(loadSidebarLayout()).toEqual({ width: expected, collapsed: true })
  expect(clampSidebarWidth(stored)).toBe(expected)
})

test('saves chosen width and collapse state without touching other preferences', () => {
  localStorage.setItem('theme', 'dark')
  saveSidebarLayout({ width: 512, collapsed: true })
  expect(loadSidebarLayout()).toEqual({ width: 512, collapsed: true })
  expect(localStorage.getItem('theme')).toBe('dark')
})

test('survives blocked browser storage for reads and writes', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('Blocked', 'SecurityError')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('Full', 'QuotaExceededError')
  })
  expect(loadSidebarLayout()).toEqual({ width: 360, collapsed: false })
  expect(() => saveSidebarLayout({ width: 420, collapsed: true })).not.toThrow()
})
