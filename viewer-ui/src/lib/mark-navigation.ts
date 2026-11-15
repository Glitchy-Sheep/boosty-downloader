import type { QueryClient } from '@tanstack/react-query'

import { markMutationKeys } from '@/lib/mark-keys'

/** Returning to a filtered tab waits for its saved marks and canonical counts. */
export async function waitForAuthorMarks(client: QueryClient, author: string, signal: AbortSignal) {
  signal.throwIfAborted()
  const pending = () => client.isMutating({ mutationKey: markMutationKeys.author(author) }) > 0
  if (!pending()) return
  await new Promise<void>((resolve, reject) => {
    const dispose = () => {
      unsubscribe()
      signal.removeEventListener('abort', abort)
    }
    const abort = () => {
      dispose()
      reject(signal.reason)
    }
    const check = () => {
      if (pending()) return
      dispose()
      resolve()
    }
    const unsubscribe = client.getMutationCache().subscribe(check)
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) abort()
    else check()
  })
}
