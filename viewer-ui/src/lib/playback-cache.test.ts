import { expect, test } from 'vitest'

import { acceptPosition } from '@/lib/playback-cache'
import { createQueryClient, postQuery } from '@/lib/queries'
import { savedPost, savedVideo } from '@/test/post-fixtures'

test('a late position response cannot restore an attachment absent from the refreshed inventory', () => {
  const client = createQueryClient()
  const key = postQuery('studio', savedPost.id).queryKey
  const current = { ...savedPost, media: [{ ...savedVideo, id: 'replacement', position_s: 0 }] }
  client.setQueryData(key, current)

  acceptPosition(client, 'studio', savedPost.id, { ...savedVideo, position_s: 75, finished: true })

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

  acceptPosition(client, 'studio', savedPost.id, { ...savedVideo, position_s: 75 })

  expect(client.getQueryData(key)?.media).toEqual([{ ...savedVideo, position_s: 75 }, sibling])
  expect(client.getQueryData(otherKey)).toEqual(savedPost)
  client.clear()
})
