import type { PostRow } from '@/lib/api.gen'
import type { Order } from '@/lib/filters'

export type PostNeighbours = { previous: PostRow | null; next: PostRow | null }
type PostOrderKey = Pick<PostRow, 'id' | 'created_at'>

function compareIds(left: string, right: string): number {
  const leftPoints = Array.from(left, character => character.codePointAt(0)!)
  const rightPoints = Array.from(right, character => character.codePointAt(0)!)
  for (let index = 0; index < Math.min(leftPoints.length, rightPoints.length); index += 1) {
    const difference = leftPoints[index] - rightPoints[index]
    if (difference) return difference
  }
  return leftPoints.length - rightPoints.length
}

function submillisecond(iso: string): number {
  const fraction = /T\d{2}:\d{2}:\d{2}\.(\d+)/.exec(iso)?.[1] ?? ''
  return Number(fraction.padEnd(6, '0').slice(3, 6))
}

/** Preserve the backend's microsecond timestamps and Unicode ID tie-break. */
export function comparePosts(left: PostOrderKey, right: PostOrderKey, order: Order): number {
  const dateOrder = Date.parse(left.created_at) - Date.parse(right.created_at)
    || submillisecond(left.created_at) - submillisecond(right.created_at)
  let ascending = dateOrder
  if (dateOrder === 0) ascending = compareIds(left.id, right.id)
  return order === 'oldest' ? ascending : -ascending
}

/** Preserve the filtered order, including an open post excluded by its filters. */
export function postNeighbours(rows: readonly PostRow[], current: PostOrderKey, order: Order = 'newest'): PostNeighbours {
  const selected = rows.findIndex(post => post.id === current.id)
  if (selected >= 0) return { previous: rows[selected - 1] ?? null, next: rows[selected + 1] ?? null }

  const following = rows.findIndex(post => comparePosts(post, current, order) > 0)
  const insertion = following < 0 ? rows.length : following
  return { previous: rows[insertion - 1] ?? null, next: rows[insertion] ?? null }
}
