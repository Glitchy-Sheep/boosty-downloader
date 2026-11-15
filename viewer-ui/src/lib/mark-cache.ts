import { hashKey, type QueryClient } from '@tanstack/react-query'

import type { Author, MarkResult, PostFilters, PostList, PostRow } from '@/lib/api.gen'
import {
  matchesMarkFilters,
  postListWithRows,
  postSummary,
  projectPostMarks,
  provenPostRow,
} from '@/lib/mark-projection'
import { pendingPostMarks } from '@/lib/mark-state'
import {
  applyMarkFields,
  isPostUnread,
  postMarkChange,
  type PostMarkChange,
  type PostMarkContext,
  type PostMarkKind,
  type PostMarkMembership,
  type PostMarkRequest,
} from '@/lib/post-marks'
import { comparePosts } from '@/lib/post-neighbours'
import { authorQuery, authorsQuery, postQuery } from '@/lib/queries'

type AuthorMarkDelta = { unseen: number; favorites: number }
export type AppliedPostMark = PostMarkContext & {
  delta: AuthorMarkDelta
}

export function createPostMarkRequest(
  client: QueryClient,
  author: string,
  source: PostRow,
  kind: PostMarkKind,
): PostMarkRequest {
  const memberships = new Map<string, PostMarkMembership>()
  for (const request of pendingPostMarks(client, author)) {
    if (request.postId !== source.id) continue
    for (const membership of request.memberships)
      memberships.set(hashKey(membership.key), membership)
  }
  for (const [key, list] of client.getQueriesData<PostList>({ queryKey: ['posts', author] })) {
    const row = list?.rows.find((post) => post.id === source.id)
    if (row) memberships.set(hashKey(key), { key, row })
  }
  return {
    author,
    postId: source.id,
    source,
    change: postMarkChange(source, kind),
    memberships: [...memberships.values()],
  }
}

export function cachedPostRow(
  client: QueryClient,
  author: string,
  postId: string,
): PostRow | undefined {
  const detail = client.getQueryData(postQuery(author, postId).queryKey)
  if (detail) return projectPostMarks(client, author, detail)
  for (const [, list] of client.getQueriesData<PostList>({ queryKey: ['posts', author] })) {
    const row = list?.rows.find((item) => item.id === postId)
    if (row) return projectPostMarks(client, author, row)
  }
  const pending = pendingPostMarks(client, author).find((request) => request.postId === postId)
  return pending && projectPostMarks(client, author, pending.source)
}

function changeAuthorCounts(client: QueryClient, author: string, delta: AuthorMarkDelta): void {
  const update = (value: Author): Author => ({
    ...value,
    unseen: Math.max(0, value.unseen + delta.unseen),
    favorites: Math.max(0, value.favorites + delta.favorites),
  })
  client.setQueryData(authorQuery(author).queryKey, (value) => value && update(value))
  client.setQueryData(authorsQuery().queryKey, (values) =>
    values?.map((value) => (value.name === author ? update(value) : value)),
  )
}

function patchRows(
  client: QueryClient,
  request: PostMarkRequest,
  update: (row: PostRow) => PostRow,
): void {
  for (const [key, list] of client.getQueriesData<PostList>({
    queryKey: ['posts', request.author],
  })) {
    if (!list) continue
    const filters = key[2] as PostFilters
    const existing = list.rows.find((row) => row.id === request.postId)
    const proven = existing ?? provenPostRow(request, filters)
    if (!proven) continue
    const latest = cachedPostRow(client, request.author, request.postId) ?? request.source
    const next = update(existing ?? postSummary(proven, latest))
    const rows = list.rows.filter((row) => row.id !== request.postId)
    if (matchesMarkFilters(next, filters)) rows.push(next)
    rows.sort((left, right) => comparePosts(left, right, filters.order))
    client.setQueryData(
      key,
      rows.length === list.rows.length ? { ...list, rows } : postListWithRows(rows),
    )
  }
}

export function applyPostMark(client: QueryClient, request: PostMarkRequest): AppliedPostMark {
  const { author, postId, source, change } = request
  const next = applyMarkFields(source, change)
  const delta = {
    unseen: Number(isPostUnread(next)) - Number(isPostUnread(source)),
    favorites: Number(next.favorite) - Number(source.favorite),
  }
  client.setQueryData(
    postQuery(author, postId).queryKey,
    (post) => post && applyMarkFields(post, change),
  )
  patchRows(client, request, (row) => applyMarkFields(row, change))
  changeAuthorCounts(client, author, delta)
  return { phase: 'writing', delta }
}

function settlePostMark(
  client: QueryClient,
  request: PostMarkRequest,
  context: AppliedPostMark,
  change: PostMarkChange,
  direction: 'next' | 'previous' = 'next',
): void {
  context.phase = 'refreshing'
  request.source = applyMarkFields(request.source, change, direction)
  // A sibling may need this field after both marks remove their only cached row.
  for (const pending of pendingPostMarks(client, request.author)) {
    if (pending.postId === request.postId)
      pending.source = applyMarkFields(pending.source, change, direction)
  }
}

export function rollbackPostMark(
  client: QueryClient,
  request: PostMarkRequest,
  context: AppliedPostMark,
): void {
  const { author, postId, change } = request
  settlePostMark(client, request, context, change, 'previous')
  client.setQueryData(
    postQuery(author, postId).queryKey,
    (post) => post && applyMarkFields(post, change, 'previous'),
  )
  patchRows(client, request, (row) =>
    projectPostMarks(client, author, applyMarkFields(row, change, 'previous'), change.kind),
  )
  changeAuthorCounts(client, author, {
    unseen: -context.delta.unseen,
    favorites: -context.delta.favorites,
  })
}

export function acceptPostMark(
  client: QueryClient,
  request: PostMarkRequest,
  result: MarkResult,
  context: AppliedPostMark,
  updateCounts: boolean,
): void {
  const { author, postId, change } = request
  const confirmed =
    change.kind === 'favorite'
      ? { ...change, next: result.post.favorite }
      : { ...change, next: { seen: result.post.seen, updated: result.post.updated } }
  settlePostMark(client, request, context, confirmed)
  client.setQueryData(
    postQuery(author, postId).queryKey,
    (post) => post && applyMarkFields(post, confirmed),
  )
  patchRows(client, request, (row) =>
    projectPostMarks(client, author, applyMarkFields(row, confirmed), change.kind),
  )
  if (!updateCounts) return
  const update = (value: Author): Author => ({
    ...value,
    unseen: result.author.unseen,
    favorites: result.author.favorites,
  })
  client.setQueryData(authorQuery(author).queryKey, (value) => value && update(value))
  client.setQueryData(authorsQuery().queryKey, (values) =>
    values?.map((value) => (value.name === author ? update(value) : value)),
  )
}
