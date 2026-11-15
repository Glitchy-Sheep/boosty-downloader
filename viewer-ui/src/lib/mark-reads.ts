import type { MutationKey, QueryClient } from '@tanstack/react-query'

export type MarkWriteContext = { phase: 'writing' | 'refreshing' }

function settledWrites(client: QueryClient, keys: readonly MutationKey[]): Set<object> {
  return new Set(
    keys.flatMap((mutationKey) =>
      client
        .getMutationCache()
        .findAll({ mutationKey })
        .filter((mutation) => {
          const context = mutation.state.context as MarkWriteContext | undefined
          return context?.phase === 'refreshing' || mutation.state.status !== 'pending'
        }),
    ),
  )
}

/** A read spanning a saved mark must finish with a fresh server snapshot. */
export async function readAfterMarkWrites<T>(
  client: QueryClient,
  keys: readonly MutationKey[],
  signal: AbortSignal,
  read: () => Promise<T>,
): Promise<T> {
  for (;;) {
    signal.throwIfAborted()
    const before = settledWrites(client, keys)
    const result = await read()
    signal.throwIfAborted()
    const after = settledWrites(client, keys)
    if (after.size === before.size && [...after].every((write) => before.has(write))) return result
  }
}
