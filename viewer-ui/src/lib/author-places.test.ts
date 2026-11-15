import { expect, test } from 'vitest'

import {
  pendingPostPlace,
  retainAuthorPlace,
  type AuthorPlaces,
  type PostsPlace,
  type ShownPlace,
} from '@/lib/author-places'
import { authorTab, isAuthorPosts } from '@/lib/author-tab'

const empty: AuthorPlaces = { shown: null, posts: undefined, media: undefined }
const reading: PostsPlace = {
  postId: 'saved',
  filters: { q: 'draft', kind: 'videos' },
  shows: 'post',
  error: undefined,
}

test('keeps the previous post and filters while the next tab loads', () => {
  const posts = retainAuthorPlace(empty, { tab: 'posts', place: reading })
  expect(retainAuthorPlace(posts, null)).toBe(posts)
  const media = retainAuthorPlace(posts, {
    tab: 'media',
    place: { filters: { view: 'images', unseen: 1 }, error: undefined },
  })
  expect(media.posts).toBe(reading)
  expect(media.shown).toBe('media')
  const back = retainAuthorPlace(media, { tab: 'posts', place: { ...reading } })
  expect(back.shown).toBe('posts')
  expect(back.media).toBe(media.media)
  expect(retainAuthorPlace(back, { tab: 'posts', place: { ...reading } })).toBe(back)
})

test('retains an empty or failed post pane and replaces its error only with new route state', () => {
  const failure = new Error('Saved post cannot be read')
  const failed = { ...reading, shows: 'error' as const, error: failure }
  const posts = retainAuthorPlace(empty, { tab: 'posts', place: failed })
  const media = retainAuthorPlace(posts, { tab: 'media', place: { filters: {}, error: undefined } })
  expect(media.posts?.error).toBe(failure)
  expect(retainAuthorPlace(media, null)).toBe(media)
  const recovered = retainAuthorPlace(media, {
    tab: 'posts',
    place: { ...reading, postId: undefined, shows: 'empty' },
  })
  expect(recovered.posts).toMatchObject({ shows: 'empty', error: undefined })
  const changed = retainAuthorPlace(recovered, {
    tab: 'posts',
    place: { ...reading, filters: { fav: 1 } },
  })
  expect(changed.posts?.filters).toEqual({ fav: 1 })
})

test('media fullscreen selection and error identity belong to the retained media place', () => {
  const place = { filters: { open: 'first' }, error: undefined }
  const first = retainAuthorPlace(empty, { tab: 'media', place })
  expect(retainAuthorPlace(first, { tab: 'media', place: { ...place } })).toBe(first)
  const next = retainAuthorPlace(first, {
    tab: 'media',
    place: { filters: { open: 'second' }, error: undefined },
  })
  expect(next.media?.filters.open).toBe('second')
  const failure = new Error('Media unavailable')
  expect(
    retainAuthorPlace(next, { tab: 'media', place: { filters: {}, error: failure } }).media?.error,
  ).toBe(failure)
})

test('tab and same-author history guards distinguish media, other authors and nested posts', () => {
  expect(authorTab('/a/studio/media')).toBe('media')
  expect(authorTab('/a/studio/media/')).toBe('media')
  expect(authorTab('/a/studio/p/media')).toBe('posts')
  expect(isAuthorPosts('/a/studio/p/first', 'studio')).toBe(true)
  expect(isAuthorPosts('/a/studio/', 'studio')).toBe(true)
  expect(isAuthorPosts('/a/studio', 'studio')).toBe(true)
  expect(isAuthorPosts('/a/studio/media', 'studio')).toBe(false)
  expect(isAuthorPosts('/a/studio-other/p/first', 'studio')).toBe(false)
  expect(isAuthorPosts('/a/%D0%B0/p/first', 'а')).toBe(true)
})

test('a pending next post cannot show old controls, including after intermediate router notifications', () => {
  const shown: ShownPlace = { tab: 'posts', place: reading }
  const previous = retainAuthorPlace(empty, shown)
  const address = { author: 'studio', postId: 'next', filters: {} }
  const loading = pendingPostPlace(previous, shown, address)
  expect(loading).toMatchObject({ tab: 'posts', place: { postId: 'next', shows: 'loading' } })
  const pending = retainAuthorPlace(previous, loading)
  expect(pendingPostPlace(pending, shown, address)).toEqual(loading)
  const ready: ShownPlace = { tab: 'posts', place: { ...reading, postId: 'next' } }
  expect(pendingPostPlace(pending, ready, address)).toBe(ready)
  expect(
    pendingPostPlace(previous, null, { ...address, postId: reading.postId ?? null }),
  ).toBeNull()
})

test('a tab switch retains outgoing content until ready, including an initial Posts entry', () => {
  const media = retainAuthorPlace(empty, { tab: 'media', place: { filters: {}, error: undefined } })
  const address = { author: 'studio', postId: 'next', filters: {} }
  expect(pendingPostPlace(media, null, address)).toBeNull()
  expect(pendingPostPlace(empty, null, address)).toBeNull()
  expect(pendingPostPlace(media, null, { ...address, postId: null })).toBeNull()
  expect(pendingPostPlace(media, null, null)).toBeNull()
})
