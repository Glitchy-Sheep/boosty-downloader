import type { PostRow } from '@/lib/api.gen'
import { formatMonth, monthKey } from '@/lib/dates'

export type MonthTarget = {
  key: string
  label: string
  year: string
  count: number
  firstPostIndex: number
}
export type MonthRow = MonthTarget & { kind: 'month' }
export type PostTimelineRow = { kind: 'post'; key: string; post: PostRow }
export type TimelineRow = MonthRow | PostTimelineRow

export type Timeline = {
  rows: TimelineRow[]
  monthIndexes: number[]
  monthTargets: MonthTarget[]
  rowIndexById: Map<string, number>
}

/** Group chronological API rows by UTC month, preserving their selected order. */
export function buildTimeline(posts: readonly PostRow[]): Timeline {
  const rows: TimelineRow[] = []
  const monthIndexes: number[] = []
  const monthTargets: MonthTarget[] = []
  const rowIndexById = new Map<string, number>()
  let month: MonthRow | undefined
  for (const post of posts) {
    const key = monthKey(post.created_at)
    if (month?.key !== key) {
      month = {
        kind: 'month',
        key,
        label: formatMonth(post.created_at),
        year: key.slice(0, 4),
        count: 0,
        firstPostIndex: rows.length + 1,
      }
      monthIndexes.push(rows.length)
      monthTargets.push(month)
      rows.push(month)
    }
    month.count += 1
    rowIndexById.set(post.id, rows.length)
    rows.push({ kind: 'post', key: post.id, post })
  }
  return { rows, monthIndexes, monthTargets, rowIndexById }
}
