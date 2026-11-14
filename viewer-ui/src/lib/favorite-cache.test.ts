import { expect, test } from 'vitest'

import type { PostDetail } from '@/lib/api.gen'
import { acceptFavorite, applyFavorite, rollbackFavorite } from '@/lib/favorite-cache'
import { acceptPosition } from '@/lib/playback-cache'
import { authorQuery, authorsQuery, createQueryClient, postQuery, postsQuery } from '@/lib/queries'
import { savedAuthor, savedList, savedPost, savedRow, savedVideo } from '@/test/post-fixtures'

function seededCache() {
  const client = createQueryClient()
  client.setQueryData(authorQuery('studio').queryKey, savedAuthor)
  client.setQueryData(authorsQuery().queryKey, [savedAuthor])
  client.setQueryData(postQuery('studio', savedPost.id).queryKey, savedPost)
  client.setQueryData(postsQuery('studio', {}).queryKey, savedList)
  client.setQueryData(postsQuery('studio', { fav: 1 }).queryKey, savedList)
  return client
}

test('optimistic unfavorite keeps filtered rows, month counts and author counts coherent', () => {
  const client = seededCache()
  applyFavorite(client, { author: 'studio', postId: savedPost.id, previous: true, favorite: false })

  expect(client.getQueryData(postsQuery('studio', { fav: 1 }).queryKey)).toEqual({ rows: [], months: [], total: 0 })
  expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(0)
  expect(client.getQueryData(authorsQuery().queryKey)?.[0].favorites).toBe(0)
  expect(client.getQueryData(postQuery('studio', savedPost.id).queryKey)?.body_html).toBe(savedPost.body_html)
  client.clear()
})

test('rollback preserves later playback, unrelated fields and another post favorite', () => {
  const client = seededCache()
  const detailKey = postQuery('studio', savedPost.id).queryKey
  const change = applyFavorite(client, { author: 'studio', postId: savedPost.id, previous: true, favorite: false })
  acceptPosition(client, 'studio', savedPost.id, { ...savedVideo, position_s: 42 })
  client.setQueryData<PostDetail>(detailKey, post => post && ({ ...post, seen: true }))
  applyFavorite(client, { author: 'studio', postId: 'other-post', previous: false, favorite: true })

  rollbackFavorite(client, change)

  expect(client.getQueryData(detailKey)).toMatchObject({ favorite: true, seen: true, body_html: savedPost.body_html, media: [{ position_s: 42 }] })
  expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(2)
  expect(client.getQueryData(postsQuery('studio', { fav: 1 }).queryKey)).toEqual(savedList)
  client.clear()
})

test('server marks merge into detail without dropping media or list search fragments', () => {
  const client = seededCache()
  const match = { title: [{ text: 'Saved', matched: true }], text: null }
  client.setQueryData(postsQuery('studio', { q: 'saved' }).queryKey, { ...savedList, rows: [{ ...savedRow, match }] })
  const before = client.getQueryData(postQuery('studio', savedPost.id).queryKey)!

  acceptFavorite(client, 'studio', { post: { ...savedRow, favorite: false }, author: { ...savedAuthor, favorites: 0 } }, true)

  const after = client.getQueryData(postQuery('studio', savedPost.id).queryKey)!
  expect(after.media).toBe(before.media)
  expect(after.body_html).toBe(before.body_html)
  expect(after.favorite).toBe(false)
  expect(client.getQueryData(postsQuery('studio', { q: 'saved' }).queryKey)?.rows[0].match).toEqual(match)
  client.clear()
})

test('late position responses preserve newer metadata and cannot recreate evicted posts', () => {
  const client = seededCache()
  const key = postQuery('studio', savedPost.id).queryKey
  client.setQueryData(key, { ...savedPost, favorite: false, media: [{ ...savedVideo, title: 'New title', removed: true }] })
  acceptPosition(client, 'studio', savedPost.id, { ...savedVideo, position_s: 32, duration_s: 101 })

  expect(client.getQueryData(key)).toMatchObject({ favorite: false, media: [{ title: 'New title', removed: true, position_s: 32, duration_s: 101 }] })
  client.removeQueries({ queryKey: key })
  acceptPosition(client, 'studio', savedPost.id, savedVideo)
  expect(client.getQueryData(key)).toBeUndefined()
  client.clear()
})

test('confirmed unfavorite removes rows from filters loaded while the write was pending', () => {
  const client = seededCache()
  applyFavorite(client, { author: 'studio', postId: savedPost.id, previous: true, favorite: false })
  const lateFilter = postsQuery('studio', { fav: 1, q: 'saved', order: 'oldest' }).queryKey
  client.setQueryData(lateFilter, savedList)

  acceptFavorite(client, 'studio', { post: { ...savedRow, favorite: false }, author: { ...savedAuthor, favorites: 0 } }, true)

  expect(client.getQueryData(lateFilter)).toEqual({ rows: [], months: [], total: 0 })
  client.clear()
})
