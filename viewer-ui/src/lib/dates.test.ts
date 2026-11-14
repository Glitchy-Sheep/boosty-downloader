import { describe, expect, it } from 'vitest'

import { formatDate, formatDay, formatMonth, monthKey } from '@/lib/dates'

describe('UTC post dates', () => {
  it('labels a post consistently with its API calendar month', () => {
    const date = '2026-09-20T18:45:00Z'
    expect(formatDay(date)).toBe('20 Sep')
    expect(formatDate(date)).toBe('20 Sep 2026')
    expect(formatMonth(date)).toBe('September 2026')
    expect(monthKey(date)).toBe('2026-09')
  })

  it('uses the previous UTC year for a positive-offset New Year timestamp', () => {
    const date = '2026-01-01T00:30:00+03:00'
    expect(formatDay(date)).toBe('31 Dec')
    expect(formatDate(date)).toBe('31 Dec 2025')
    expect(formatMonth(date)).toBe('December 2025')
    expect(monthKey(date)).toBe('2025-12')
  })

  it('uses the next UTC month for a negative-offset month boundary', () => {
    const date = '2024-02-29T23:30:00-02:00'
    expect(formatDay(date)).toBe('1 Mar')
    expect(formatDate(date)).toBe('1 Mar 2024')
    expect(formatMonth(date)).toBe('March 2024')
    expect(monthKey(date)).toBe('2024-03')
  })
})
