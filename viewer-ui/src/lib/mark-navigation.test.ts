import { MutationObserver } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'

import { markMutationKeys } from '@/lib/mark-keys'
import { waitForAuthorMarks } from '@/lib/mark-navigation'
import { createQueryClient } from '@/lib/queries'

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

test('navigation waits for both the mark write and its canonical refresh, only for this author', async () => {
  const client = createQueryClient()
  const saved = deferred()
  const refreshed = deferred()
  const observer = new MutationObserver(client, {
    mutationKey: markMutationKeys.single('studio', 'post', 'favorite'),
    mutationFn: () => saved.promise,
    onSettled: () => refreshed.promise,
  })
  const writing = observer.mutate()
  const controller = new AbortController()
  const arrived = vi.fn()
  const entering = waitForAuthorMarks(client, 'studio', controller.signal).then(arrived)
  await waitForAuthorMarks(client, 'another', controller.signal)
  expect(arrived).not.toHaveBeenCalled()
  saved.resolve()
  await Promise.resolve()
  expect(arrived).not.toHaveBeenCalled()
  refreshed.resolve()
  await Promise.all([writing, entering])
  expect(arrived).toHaveBeenCalledOnce()
  client.clear()
})

test('leaving a pending navigation removes its subscription without interrupting the saved mark', async () => {
  const client = createQueryClient()
  const saved = deferred()
  const observer = new MutationObserver(client, {
    mutationKey: markMutationKeys.bulk('studio'),
    mutationFn: () => saved.promise,
  })
  const writing = observer.mutate()
  const controller = new AbortController()
  const entering = waitForAuthorMarks(client, 'studio', controller.signal)
  const rejected = expect(entering).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  await rejected
  expect(client.isMutating()).toBe(1)
  saved.resolve()
  await writing
  await expect(waitForAuthorMarks(client, 'studio', controller.signal)).rejects.toMatchObject({
    name: 'AbortError',
  })
  client.clear()
})

test('a failed write still releases navigation after reconciliation', async () => {
  const client = createQueryClient()
  const saved = deferred()
  const observer = new MutationObserver(client, {
    mutationKey: markMutationKeys.single('studio', 'post', 'seen'),
    mutationFn: async () => {
      await saved.promise
      throw new Error('Storage unavailable')
    },
  })
  const writing = expect(observer.mutate()).rejects.toThrow('Storage unavailable')
  const entering = waitForAuthorMarks(client, 'studio', new AbortController().signal)
  saved.resolve()
  await Promise.all([writing, entering])
  client.clear()
})
