import { MutationObserver, QueryClientProvider, type MutationKey } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, test } from 'vitest'

import { usePlayerPositions } from '@/hooks/use-player-positions'
import type { MediaItem, MediaPage } from '@/lib/api.gen'
import { markMutationKeys } from '@/lib/mark-keys'
import { playbackMutationKeys } from '@/lib/playback-keys'
import { createPlayerStore, currentTrack, PlayerProvider } from '@/lib/player'
import { createQueryClient } from '@/lib/queries'
import { playbackItem } from '@/test/playback-fixture'

const item = playbackItem({ kind: 'audio' })
const page: MediaPage = {
  items: [item],
  missing: 0,
  counts: { all: 1, audio: 1, videos: 0, images: 0, files: 0 },
  posts: {
    post: { access: 'open', title: 'Post', seen: false, favorite: false, cover_path: null },
  },
}

function setup() {
  const client = createQueryClient()
  const store = createPlayerStore()
  store.start('author', page, item.id)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <PlayerProvider store={store}>{children}</PlayerProvider>
    </QueryClientProvider>
  )
  const hook = renderHook(usePlayerPositions, { wrapper })
  const publish = (mutationKey: MutationKey, saved: MediaItem) =>
    new MutationObserver(client, { mutationKey, mutationFn: async () => saved }).mutate()
  return { ...hook, client, store, publish }
}

test('only successful playback for the queued author updates its canonical item', async () => {
  const { client, store, publish, unmount } = setup()
  const snapshot = store.getSnapshot()
  const saved = { ...item, position_s: 75, finished: true }
  await act(() => publish(markMutationKeys.single('author', item.post_id, 'favorite'), saved))
  await act(() => publish(playbackMutationKeys.media('another', item.post_id, item.id), saved))
  expect(store.getSnapshot()).toBe(snapshot)
  await act(() => publish(playbackMutationKeys.media('author', item.post_id, item.id), saved))
  expect(currentTrack(store.getSnapshot())).toEqual(saved)
  expect(store.getSnapshot()?.request).toBe(snapshot?.request)
  unmount()
  client.clear()
})

test('failed persistence and saves after the shell detaches do not replace queue positions', async () => {
  const { client, store, publish, unmount } = setup()
  const snapshot = store.getSnapshot()
  const mutationKey = playbackMutationKeys.media('author', item.post_id, item.id)
  const failure = new MutationObserver(client, {
    mutationKey,
    mutationFn: async () => {
      throw new Error('Disk full')
    },
  })
  await act(async () => {
    await expect(failure.mutate()).rejects.toThrow('Disk full')
  })
  expect(store.getSnapshot()).toBe(snapshot)
  unmount()
  await publish(mutationKey, { ...item, position_s: 75 })
  expect(store.getSnapshot()).toBe(snapshot)
  client.clear()
})
