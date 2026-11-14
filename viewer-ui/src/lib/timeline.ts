import type { PostRow } from '@/lib/api.gen'
import { formatMonth, monthKey } from '@/lib/dates'

export type MonthRow = { kind: 'month'; key: string; label: string; count: number }
export type PostTimelineRow = { kind: 'post'; key: string; post: PostRow }
export type TimelineRow = MonthRow | PostTimelineRow

export type Timeline = {
  rows: TimelineRow[]
  monthIndexes: number[]
  rowIndexById: Map<string, number>
}

/** Group chronological API rows by UTC month, preserving their selected order. */
export function buildTimeline(posts: readonly PostRow[]): Timeline {
  const rows: TimelineRow[] = []
  const monthIndexes: number[] = []
  const rowIndexById = new Map<string, number>()
  let month: MonthRow | undefined
  for (const post of posts) {
    const key = monthKey(post.created_at)
    if (month?.key !== key) {
      month = { kind: 'month', key, label: formatMonth(post.created_at), count: 0 }
      monthIndexes.push(rows.length)
      rows.push(month)
    }
    month.count += 1
    rowIndexById.set(post.id, rows.length)
    rows.push({ kind: 'post', key: post.id, post })
  }
  return { rows, monthIndexes, rowIndexById }
}
