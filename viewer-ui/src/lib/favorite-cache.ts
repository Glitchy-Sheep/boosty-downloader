import type { QueryClient, QueryKey } from '@tanstack/react-query'

import type { Author, MarkResult, PostFilters, PostList, PostRow } from '@/lib/api.gen'
import { monthKey } from '@/lib/dates'
import { comparePosts } from '@/lib/post-neighbours'
import { authorQuery, authorsQuery, postQuery } from '@/lib/queries'

type RemovedFavorite = { key: QueryKey; row: PostRow }
export type FavoriteChange = {
  author: string
  postId: string
  previous: boolean
  favorite: boolean
  removed: RemovedFavorite[]
}

function withRows(rows: PostRow[]): PostList {
  const counts = new Map<string, number>()
  for (const row of rows) {
    const month = monthKey(row.created_at)
    counts.set(month, (counts.get(month) ?? 0) + 1)
  }
  return { rows, months: [...counts].map(([month, count]) => ({ month, count })), total: rows.length }
}

function changeAuthorCount(client: QueryClient, author: string, delta: number): void {
  const update = (value: Author): Author => ({ ...value, favorites: Math.max(0, value.favorites + delta) })
  client.setQueryData(authorQuery(author).queryKey, value => value && update(value))
  client.setQueryData(authorsQuery().queryKey, values => values?.map(value => value.name === author ? update(value) : value))
}

/** Change only the favorite field; playback, seen and freshly loaded metadata survive. */
export function applyFavorite(client: QueryClient, change: Omit<FavoriteChange, 'removed'>): FavoriteChange {
  const { author, postId, favorite, previous } = change
  const removed: RemovedFavorite[] = []
  client.setQueryData(postQuery(author, postId).queryKey, post => post && ({ ...post, favorite }))
  for (const [key, list] of client.getQueriesData<PostList>({ queryKey: ['posts', author] })) {
    if (!list) continue
    const filters = key[2] as PostFilters
    const index = list.rows.findIndex(row => row.id === postId)
    if (index < 0) continue
    if (filters.fav && !favorite) {
      removed.push({ key, row: list.rows[index] })
      client.setQueryData(key, withRows(list.rows.filter(row => row.id !== postId)))
    } else {
      client.setQueryData(key, { ...list, rows: list.rows.map(row => row.id === postId ? { ...row, favorite } : row) })
    }
  }
  changeAuthorCount(client, author, Number(favorite) - Number(previous))
  return { ...change, removed }
}

export function rollbackFavorite(client: QueryClient, change: FavoriteChange): void {
  applyFavorite(client, { ...change, favorite: change.previous, previous: change.favorite })
  for (const { key, row } of change.removed) {
    client.setQueryData<PostList>(key, current => {
      if (!current || current.rows.some(item => item.id === row.id)) return current
      const filters = key[2] as PostFilters
      const rows = [...current.rows, row].sort((left, right) => comparePosts(left, right, filters.order))
      return withRows(rows)
    })
  }
}

export function acceptFavorite(client: QueryClient, author: string, result: MarkResult, updateCounts: boolean): void {
  client.setQueryData(postQuery(author, result.post.id).queryKey, post => post && ({ ...post, ...result.post }))
  for (const [key, list] of client.getQueriesData<PostList>({ queryKey: ['posts', author] })) {
    if (!list) continue
    const filters = key[2] as PostFilters
    if (filters.fav && !result.post.favorite) {
      client.setQueryData(key, withRows(list.rows.filter(row => row.id !== result.post.id)))
    } else {
      client.setQueryData(key, {
        ...list,
        rows: list.rows.map(row => row.id === result.post.id ? { ...row, ...result.post, match: row.match } : row),
      })
    }
  }
  if (!updateCounts) return
  client.setQueryData(authorQuery(author).queryKey, result.author)
}
