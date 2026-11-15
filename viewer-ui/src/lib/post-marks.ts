import type { QueryKey } from '@tanstack/react-query'

import type { MediaPost, PostRow } from '@/lib/api.gen'
import type { WriteContext } from '@/lib/mutation-reads'

export type PostMarkMembership = { key: QueryKey; row: PostRow }

export type PostMarkKind = 'seen' | 'favorite'
export type PostSeenState = Pick<PostRow, 'seen' | 'updated'>

export type PostMarkChange =
  | { kind: 'seen'; previous: PostSeenState; next: PostSeenState }
  | { kind: 'favorite'; previous: boolean; next: boolean }

export type PostMarkSource = { kind: 'post'; row: PostRow } | { kind: 'media'; post: MediaPost }

export type PostMarkRequest = {
  author: string
  postId: string
  source: PostMarkSource
  change: PostMarkChange
  memberships: PostMarkMembership[]
}

export type PostMarkContext = WriteContext

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

export function applyMediaMark(
  post: MediaPost,
  change: PostMarkChange,
  direction: 'next' | 'previous' = 'next',
): MediaPost {
  switch (change.kind) {
    case 'favorite':
      return { ...post, favorite: change[direction] }
    case 'seen':
      return { ...post, seen: change[direction].seen }
  }
}

export function applySourceMark(
  source: PostMarkSource,
  change: PostMarkChange,
  direction: 'next' | 'previous' = 'next',
): PostMarkSource {
  switch (source.kind) {
    case 'post':
      return { kind: 'post', row: applyMarkFields(source.row, change, direction) }
    case 'media':
      return { kind: 'media', post: applyMediaMark(source.post, change, direction) }
  }
}
