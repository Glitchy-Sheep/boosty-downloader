import { hashKey, type QueryClient } from '@tanstack/react-query'

import type { Author, PostFilters, PostList, PostRow } from '@/lib/api.gen'
import { monthKey } from '@/lib/dates'
import { pendingPostMarks } from '@/lib/mark-state'
import {
  applyMarkFields,
  isPostUnread,
  type PostMarkKind,
  type PostMarkRequest,
} from '@/lib/post-marks'
import { comparePosts } from '@/lib/post-neighbours'

export function postListWithRows(rows: PostRow[]): PostList {
  const counts = new Map<string, number>()
  for (const row of rows) {
    const month = monthKey(row.created_at)
    counts.set(month, (counts.get(month) ?? 0) + 1)
  }
  return {
    rows,
    months: [...counts].map(([month, count]) => ({ month, count })),
    total: rows.length,
  }
}

export function matchesMarkFilters(post: PostRow, filters: PostFilters): boolean {
  return (!filters.fav || post.favorite) && (!filters.unseen || isPostUnread(post))
}

function membershipScope(filters: PostFilters): string {
  const { q, tag, kind, locked, incomplete } = filters
  return hashKey([{ q, tag, kind, locked, incomplete }])
}

/** Preserve the destination search fragments without copying detail-only fields. */
export function postSummary(row: PostRow, latest: PostRow): PostRow {
  return {
    id: latest.id,
    title: latest.title,
    created_at: latest.created_at,
    access: latest.access,
    counts: latest.counts,
    cover_path: latest.cover_path,
    missing_media: latest.missing_media,
    tier: latest.tier,
    seen: latest.seen,
    updated: latest.updated,
    favorite: latest.favorite,
    match: row.match,
  }
}

/** Search, tag and media membership must be proven by an equivalent server query. */
export function provenPostRow(request: PostMarkRequest, filters: PostFilters): PostRow | undefined {
  const scope = membershipScope(filters)
  const membership = request.memberships.find(
    (item) => membershipScope(item.key[2] as PostFilters) === scope,
  )
  if (membership) return membership.row
  if (filters.q || filters.tag || filters.kind || filters.locked || filters.incomplete)
    return undefined
  return { ...postSummary(request.source, request.source), match: null }
}

export function projectPostMarks<T extends PostRow>(
  client: QueryClient,
  author: string,
  post: T,
  except?: PostMarkKind,
): T {
  return withPendingMarks(post, pendingPostMarks(client, author), except)
}

function withPendingMarks<T extends PostRow>(
  post: T,
  requests: readonly PostMarkRequest[],
  except?: PostMarkKind,
): T {
  return requests.reduce((current, request) => {
    if (request.postId !== post.id || request.change.kind === except) return current
    return applyMarkFields(current, request.change)
  }, post)
}

/** A newly opened query must not replace an in-flight optimistic mark with stale data. */
export function projectPostList(
  client: QueryClient,
  author: string,
  filters: PostFilters,
  list: PostList,
): PostList {
  const pending = pendingPostMarks(client, author)
  if (!pending.length) return list
  const key = ['posts', author, filters]
  const queryHash = hashKey(key)
  for (const request of pending) {
    const row = list.rows.find((post) => post.id === request.postId)
    if (!row) continue
    request.source = row
    const previous = request.memberships.findIndex((item) => hashKey(item.key) === queryHash)
    const membership = { key, row }
    if (previous === -1) request.memberships.push(membership)
    else request.memberships[previous] = membership
  }
  const rows = list.rows
    .map((row) => withPendingMarks(row, pending))
    .filter((row) => matchesMarkFilters(row, filters))
  for (const request of pending) {
    if (rows.some((row) => row.id === request.postId)) continue
    const proven = provenPostRow(request, filters)
    if (!proven) continue
    const row = withPendingMarks(postSummary(proven, request.source), pending)
    if (matchesMarkFilters(row, filters)) rows.push(row)
  }
  rows.sort((left, right) => comparePosts(left, right, filters.order))
  return postListWithRows(rows)
}

export function projectAuthorMarks(client: QueryClient, author: Author): Author {
  if (!pendingPostMarks(client, author.name).length) return author
  const cached =
    client.getQueryData<Author>(['author', author.name]) ??
    client.getQueryData<Author[]>(['authors'])?.find((item) => item.name === author.name)
  if (!cached) return author
  return { ...author, unseen: cached.unseen, favorites: cached.favorites }
}
