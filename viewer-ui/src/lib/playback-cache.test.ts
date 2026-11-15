import { expect, test } from 'vitest'

import { acceptPosition } from '@/lib/playback-cache'
import { createQueryClient, mediaQuery, postQuery } from '@/lib/queries'
import { savedMediaPage } from '@/test/media-fixtures'
import { savedPost, savedVideo } from '@/test/post-fixtures'

test('a late position response cannot restore an attachment absent from the refreshed inventory', () => {
  const client = createQueryClient()
  const key = postQuery('studio', savedPost.id).queryKey
  const current = { ...savedPost, media: [{ ...savedVideo, id: 'replacement', position_s: 0 }] }
  client.setQueryData(key, current)

  acceptPosition(
    client,
    'studio',
    savedPost.id,
    { ...savedVideo, position_s: 75, finished: true },
    savedVideo.finished,
  )

  expect(client.getQueryData(key)).toEqual(current)
  client.clear()
})

test('a position response changes only its own attachment in its author and post', () => {
  const client = createQueryClient()
  const key = postQuery('studio', savedPost.id).queryKey
  const otherKey = postQuery('another-author', savedPost.id).queryKey
  const sibling = { ...savedVideo, id: 'other-video', position_s: 12 }
  client.setQueryData(key, { ...savedPost, media: [savedVideo, sibling] })
  client.setQueryData(otherKey, savedPost)

  acceptPosition(
    client,
    'studio',
    savedPost.id,
    { ...savedVideo, position_s: 75 },
    savedVideo.finished,
  )

  expect(client.getQueryData(key)?.media).toEqual([{ ...savedVideo, position_s: 75 }, sibling])
  expect(client.getQueryData(otherKey)).toEqual(savedPost)
  client.clear()
})

test('Media playback preserves inventory, metadata and other authors while updating only playback fields', () => {
  const client = createQueryClient()
  const key = mediaQuery('studio', {}).queryKey
  const unseen = mediaQuery('studio', { unseen: 1 }).queryKey
  const otherAuthor = mediaQuery('another-author', {}).queryKey
  const sibling = { ...savedVideo, id: 'other', position_s: 10 }
  const current = { ...savedMediaPage, items: [savedVideo, sibling] }
  client.setQueryData(key, current)
  client.setQueryData(unseen, current)
  client.setQueryData(otherAuthor, current)
  acceptPosition(
    client,
    'studio',
    savedPost.id,
    {
      ...savedVideo,
      title: 'Unrelated old title',
      position_s: 75,
      duration_s: 95,
    },
    savedVideo.finished,
  )
  const expected = {
    ...current,
    items: [{ ...savedVideo, position_s: 75, duration_s: 95 }, sibling],
  }
  expect(client.getQueryData(key)).toEqual(expected)
  expect(client.getQueryData(unseen)).toEqual(expected)
  expect(client.getQueryData(otherAuthor)).toEqual(current)
  expect(client.getQueryState(unseen)?.isInvalidated).toBe(false)
  expect(client.getQueryData(postQuery('studio', savedPost.id).queryKey)).toBeUndefined()
  acceptPosition(
    client,
    'studio',
    savedPost.id,
    { ...savedVideo, position_s: 0, finished: true },
    savedVideo.finished,
  )
  expect(client.getQueryData(key)?.items[0]?.finished).toBe(true)
  expect(client.getQueryState(unseen)?.isInvalidated).toBe(true)
  client.clear()
})

test('late playback cannot add a missing Media item or change an item from another post', () => {
  const client = createQueryClient()
  const key = mediaQuery('studio', {}).queryKey
  const current = { ...savedMediaPage, items: [{ ...savedVideo, post_id: 'another-post' }] }
  client.setQueryData(key, current)
  acceptPosition(
    client,
    'studio',
    savedPost.id,
    { ...savedVideo, position_s: 80 },
    savedVideo.finished,
  )
  expect(client.getQueryData(key)).toEqual(current)
  expect(client.getQueryState(key)?.isInvalidated).toBe(false)
  client.clear()
})
