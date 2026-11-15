export type TimelineMeasurement = {
  key: string | number | bigint
  index: number
  start: number
  end: number
  size: number
}

/** The first unobscured row and the reader's position within it. */
export type TimelineAnchor = {
  key: TimelineMeasurement['key']
  index: number
  inside: number
}

export type TimelineExtent = { height: string; minHeight: number }

export function timelineAnchorAt(
  measurements: readonly TimelineMeasurement[],
  scrollOffset: number,
  topInset: number,
): TimelineAnchor | null {
  const top = scrollOffset + topInset
  let first = 0
  let last = measurements.length
  while (first < last) {
    const middle = Math.floor((first + last) / 2)
    const row = measurements[middle]
    if (!row || row.end > top) last = middle
    else first = middle + 1
  }
  const row = measurements[first]
  if (!row) return null
  return { key: row.key, index: row.index, inside: top - row.start }
}

/** Resolve a saved row after resize; changed data may have moved or removed it. */
export function timelineAnchorOffset(
  anchor: TimelineAnchor,
  measurements: readonly TimelineMeasurement[],
  topInset: number,
): number | null {
  let row = measurements[anchor.index]
  if (row?.key !== anchor.key) row = measurements.find((item) => item.key === anchor.key)
  if (!row) return null
  const inside = Math.min(anchor.inside, row.size - 1)
  return Math.max(0, row.start + inside - topInset)
}

/** Viewport growth reserves the anchor's scroll range in the same layout pass. */
export function timelineExtent(logicalHeight: number, minimumScrollOffset: number): TimelineExtent {
  return { height: `calc(100% + ${minimumScrollOffset}px)`, minHeight: logicalHeight }
}
