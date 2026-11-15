import type { QueryKey } from '@tanstack/react-query'

import type { PostRow } from '@/lib/api.gen'
import type { MarkWriteContext } from '@/lib/mark-reads'

export type PostMarkMembership = { key: QueryKey; row: PostRow }

export type PostMarkKind = 'seen' | 'favorite'
export type PostSeenState = Pick<PostRow, 'seen' | 'updated'>

export type PostMarkChange =
  | { kind: 'seen'; previous: PostSeenState; next: PostSeenState }
  | { kind: 'favorite'; previous: boolean; next: boolean }

export type PostMarkRequest = {
  author: string
  postId: string
  source: PostRow
  change: PostMarkChange
  memberships: PostMarkMembership[]
}

export type PostMarkContext = MarkWriteContext

/** Newly added content makes a previously seen post unread again. */
export function isPostUnread(post: Pick<PostRow, 'access' | 'seen' | 'updated'>): boolean {
  return post.access === 'open' && (!post.seen || post.updated)
}

export function nextSeenMark(post: Pick<PostRow, 'access' | 'seen' | 'updated'>): boolean {
  return isPostUnread(post)
}

export function countMarkChanges(posts: readonly PostRow[], seen: boolean): number {
  return posts.filter((post) => {
    if (post.access === 'locked') return false
    return seen ? isPostUnread(post) : post.seen
  }).length
}

export function postMarkChange(post: PostRow, kind: PostMarkKind): PostMarkChange {
  switch (kind) {
    case 'seen':
      return {
        kind,
        previous: { seen: post.seen, updated: post.updated },
        next: { seen: nextSeenMark(post), updated: false },
      }
    case 'favorite':
      return { kind, previous: post.favorite, next: !post.favorite }
  }
}

export function applyMarkFields<T extends PostRow>(
  post: T,
  change: PostMarkChange,
  direction: 'next' | 'previous' = 'next',
): T {
  switch (change.kind) {
    case 'seen':
      return { ...post, ...change[direction] }
    case 'favorite':
      return { ...post, favorite: change[direction] }
  }
}
