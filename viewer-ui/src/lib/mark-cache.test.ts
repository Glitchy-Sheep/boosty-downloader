import { expect, test } from 'vitest'

import type { PostDetail } from '@/lib/api.gen'
import type { Filters } from '@/lib/filters'
import {
  acceptPostMark,
  applyPostMark,
  createPostMarkRequest,
  rollbackPostMark,
} from '@/lib/mark-cache'
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
  applyPostMark(client, createPostMarkRequest(client, 'studio', savedRow, 'favorite'))

  expect(client.getQueryData(postsQuery('studio', { fav: 1 }).queryKey)).toEqual({
    rows: [],
    months: [],
    total: 0,
  })
  expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(0)
  expect(client.getQueryData(authorsQuery().queryKey)?.[0]?.favorites).toBe(0)
  expect(client.getQueryData(postQuery('studio', savedPost.id).queryKey)?.body_html).toBe(
    savedPost.body_html,
  )
  client.clear()
})

test('rollback preserves later playback, metadata, seen and another post favorite', () => {
  const client = seededCache()
  const detailKey = postQuery('studio', savedPost.id).queryKey
  const request = createPostMarkRequest(client, 'studio', savedRow, 'favorite')
  const context = applyPostMark(client, request)
  acceptPosition(
    client,
    'studio',
    savedPost.id,
    { ...savedVideo, position_s: 42 },
    savedVideo.finished,
  )
  client.setQueryData<PostDetail>(
    detailKey,
    (post) => post && { ...post, seen: true, title: 'Fresh title' },
  )
  applyPostMark(
    client,
    createPostMarkRequest(
      client,
      'studio',
      { ...savedRow, id: 'other', favorite: false },
      'favorite',
    ),
  )

  rollbackPostMark(client, request, context)

  expect(client.getQueryData(detailKey)).toMatchObject({
    favorite: true,
    seen: true,
    title: 'Fresh title',
    body_html: savedPost.body_html,
    media: [{ position_s: 42 }],
  })
  expect(client.getQueryData(authorQuery('studio').queryKey)?.favorites).toBe(2)
  expect(client.getQueryData(postsQuery('studio', { fav: 1 }).queryKey)?.rows).toEqual([
    { ...savedRow, id: 'other', favorite: true },
    { ...savedRow, seen: true, title: 'Fresh title' },
  ])
  client.clear()
})

test('confirmed favorite owns only its field, preserving seen, media and search fragments', () => {
  const client = seededCache()
  const match = { title: [{ text: 'Saved', matched: true }], text: null }
  client.setQueryData(postsQuery('studio', { q: 'saved' }).queryKey, {
    ...savedList,
    rows: [{ ...savedRow, match, seen: true }],
  })
  client.setQueryData(postQuery('studio', savedPost.id).queryKey, {
    ...savedPost,
    seen: true,
    title: 'New title',
  })
  const request = createPostMarkRequest(client, 'studio', savedRow, 'favorite')
  const context = applyPostMark(client, request)
  const before = client.getQueryData(postQuery('studio', savedPost.id).queryKey)!

  acceptPostMark(
    client,
    request,
    { post: { ...savedRow, favorite: false }, author: { ...savedAuthor, favorites: 0 } },
    context,
    true,
  )

  const after = client.getQueryData(postQuery('studio', savedPost.id).queryKey)!
  expect(after.media).toBe(before.media)
  expect(after.body_html).toBe(before.body_html)
  expect(after).toMatchObject({ favorite: false, seen: true, title: 'New title' })
  expect(client.getQueryData(postsQuery('studio', { q: 'saved' }).queryKey)?.rows[0]).toMatchObject(
    { seen: true, match },
  )
  expect(client.getQueryData(authorsQuery().queryKey)?.[0]?.favorites).toBe(0)
  client.clear()
})

test('late position responses preserve newer metadata and cannot recreate evicted posts', () => {
  const client = seededCache()
  const key = postQuery('studio', savedPost.id).queryKey
  client.setQueryData(key, {
    ...savedPost,
    favorite: false,
    media: [{ ...savedVideo, title: 'New title', removed: true }],
  })
  acceptPosition(
    client,
    'studio',
    savedPost.id,
    { ...savedVideo, position_s: 32, duration_s: 101 },
    savedVideo.finished,
  )
  expect(client.getQueryData(key)).toMatchObject({
    favorite: false,
    media: [{ title: 'New title', removed: true, position_s: 32, duration_s: 101 }],
  })
  client.removeQueries({ queryKey: key })
  acceptPosition(client, 'studio', savedPost.id, savedVideo, savedVideo.finished)
  expect(client.getQueryData(key)).toBeUndefined()
  client.clear()
})

test('confirmed unfavorite removes rows from filters loaded while the write was pending', () => {
  const client = seededCache()
  const request = createPostMarkRequest(client, 'studio', savedRow, 'favorite')
  const context = applyPostMark(client, request)
  const lateFilter = postsQuery('studio', { fav: 1, q: 'saved', order: 'oldest' }).queryKey
  client.setQueryData(lateFilter, savedList)
  acceptPostMark(
    client,
    request,
    { post: { ...savedRow, favorite: false }, author: { ...savedAuthor, favorites: 0 } },
    context,
    true,
  )
  expect(client.getQueryData(lateFilter)).toEqual({ rows: [], months: [], total: 0 })
  client.clear()
})

test('seen rollback restores Updated without dropping an unrelated favorite or new body', () => {
  const client = seededCache()
  const updated = { ...savedRow, seen: true, updated: true }
  const key = postQuery('studio', savedRow.id).queryKey
  client.setQueryData(key, { ...savedPost, ...updated })
  client.setQueryData(postsQuery('studio', { unseen: 1 }).queryKey, {
    ...savedList,
    rows: [updated],
  })
  const request = createPostMarkRequest(client, 'studio', updated, 'seen')
  const context = applyPostMark(client, request)
  expect(client.getQueryData(key)).toMatchObject({ seen: true, updated: false })
  expect(client.getQueryData(postsQuery('studio', { unseen: 1 }).queryKey)?.total).toBe(0)
  client.setQueryData(
    key,
    (post) => post && { ...post, favorite: false, body_html: '<p>Fresh</p>' },
  )
  rollbackPostMark(client, request, context)
  expect(client.getQueryData(key)).toMatchObject({
    seen: true,
    updated: true,
    favorite: false,
    body_html: '<p>Fresh</p>',
  })
  expect(client.getQueryData(postsQuery('studio', { unseen: 1 }).queryKey)?.rows[0]).toMatchObject({
    seen: true,
    updated: true,
    favorite: false,
  })
  expect(client.getQueryData(authorQuery('studio').queryKey)?.unseen).toBe(savedAuthor.unseen)
  client.clear()
})

test('new favorites enter equivalent cached scopes with their search fragments and destination order', () => {
  const client = createQueryClient()
  const match = { title: [{ text: 'Saved', matched: true }], text: null }
  const row = { ...savedRow, favorite: false, match }
  const scope: Filters = { q: 'saved', tag: 'winter', kind: 'videos', incomplete: 1 }
  client.setQueryData(postsQuery('studio', scope).queryKey, { ...savedList, rows: [row] })
  const destination = postsQuery('studio', { ...scope, fav: 1, order: 'oldest' }).queryKey
  const later = { ...savedRow, id: 'later', created_at: '2026-02-01T00:00:00Z', match }
  client.setQueryData(destination, {
    rows: [later],
    total: 1,
    months: [{ month: '2026-02', count: 1 }],
  })
  const unrelated: Filters[] = [
    { ...scope, fav: 1, q: 'different' },
    { ...scope, fav: 1, tag: 'summer' },
    { ...scope, fav: 1, kind: 'images' },
    { ...scope, fav: 1, locked: 1 },
    { ...scope, fav: 1, incomplete: undefined },
  ]
  for (const filters of unrelated)
    client.setQueryData(postsQuery('studio', filters).queryKey, { rows: [], total: 0, months: [] })

  const request = createPostMarkRequest(client, 'studio', row, 'favorite')
  const context = applyPostMark(client, request)

  expect(client.getQueryData(destination)).toEqual({
    rows: [{ ...row, favorite: true }, later],
    total: 2,
    months: [
      { month: '2026-01', count: 1 },
      { month: '2026-02', count: 1 },
    ],
  })
  for (const filters of unrelated)
    expect(client.getQueryData(postsQuery('studio', filters).queryKey)?.rows).toEqual([])
  rollbackPostMark(client, request, context)
  expect(client.getQueryData(destination)).toEqual({
    rows: [later],
    total: 1,
    months: [{ month: '2026-02', count: 1 }],
  })
  client.clear()
})

test('marking a detail unread inserts only a post summary into cached Unseen', () => {
  const client = createQueryClient()
  const row = { ...savedPost, seen: true, updated: false }
  const unseen = postsQuery('studio', { unseen: 1 }).queryKey
  client.setQueryData(postQuery('studio', row.id).queryKey, row)
  client.setQueryData(authorQuery('studio').queryKey, savedAuthor)
  client.setQueryData(unseen, { rows: [], total: 0, months: [] })
  const request = createPostMarkRequest(client, 'studio', row, 'seen')
  const context = applyPostMark(client, request)
  expect(client.getQueryData(unseen)).toEqual(savedList)
  expect(client.getQueryData(authorQuery('studio').queryKey)?.unseen).toBe(savedAuthor.unseen + 1)
  rollbackPostMark(client, request, context)
  expect(client.getQueryData(unseen)).toEqual({ rows: [], total: 0, months: [] })
  expect(client.getQueryData(authorQuery('studio').queryKey)?.unseen).toBe(savedAuthor.unseen)
  client.clear()
})
