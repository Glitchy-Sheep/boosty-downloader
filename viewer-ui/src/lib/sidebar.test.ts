import { describe, expect, it } from 'vitest'

import { rowMetrics } from '@/lib/sidebar'

describe('sidebar row geometry', () => {
  it('bounds narrow and wide layouts at the approved sizes', () => {
    expect(rowMetrics(260)).toMatchObject({ coverWidth: 64, gap: 10, padX: 12, titleSize: 13.5, height: 75 })
    expect(rowMetrics(510)).toMatchObject({ coverWidth: 144, gap: 14, padX: 16, titleSize: 15, height: 101 })
    expect(rowMetrics(0)).toEqual(rowMetrics(260))
    expect(rowMetrics(200)).toEqual(rowMetrics(260))
    expect(rowMetrics(640)).toEqual(rowMetrics(510))
  })

  it('grows cover and typography continuously through intermediate widths', () => {
    const middle = rowMetrics(385)
    expect(middle.coverWidth).toBe(104)
    expect(middle.gap).toBe(12)
    expect(middle.titleSize).toBe(14.25)
    for (let width = 261; width <= 510; width += 1) {
      const previous = rowMetrics(width - 1)
      const current = rowMetrics(width)
      expect(current.coverWidth - previous.coverWidth).toBeCloseTo(0.32)
      expect(current.height).toBeGreaterThanOrEqual(previous.height)
      expect(current.padX).toBeGreaterThanOrEqual(12)
    }
  })

  it('reserves enough height for metadata and two snippet lines', () => {
    for (const width of [260, 320, 360, 385, 450, 510, 640]) {
      const metrics = rowMetrics(width)
      expect(metrics.snippetHeight).toBeGreaterThanOrEqual(metrics.height)
      expect(metrics.snippetHeight).toBeGreaterThanOrEqual(2 * metrics.titleLeading + 4 + 16 + 32 + 4 + 20 - 0.5)
      expect(metrics.height).toBeGreaterThanOrEqual(metrics.coverWidth * 9 / 16 + 20 - 0.5)
      expect(metrics.titleLines).toBeGreaterThanOrEqual(2)
      expect(metrics.titleLines).toBeLessThanOrEqual(3)
    }
  })
})
