import type { MutationKey, QueryClient, QueryKey } from '@tanstack/react-query'

export type WriteContext = { phase: 'writing' | 'refreshing' }

/** Reconcile in-flight route snapshots without cancelling their loader promises. */
export async function settleActiveReads(
  client: QueryClient,
  keys: readonly QueryKey[],
): Promise<void> {
  const queries = new Set(
    keys.flatMap((queryKey) =>
      client.getQueryCache().findAll({ queryKey, fetchStatus: 'fetching' }),
    ),
  )
  const pending = [...queries].flatMap((query) =>
    query.promise ? [{ query, promise: query.promise }] : [],
  )
  const results = await Promise.allSettled(pending.map((read) => read.promise))
  // Initial loaders also need canonical membership and counts at the commit boundary.
  const completed = new Set(
    pending
      .filter((_read, index) => results[index]?.status === 'fulfilled')
      .map((read) => read.query),
  )
  await client.refetchQueries({ type: 'inactive', predicate: (query) => completed.has(query) })
}

function settledWrites(client: QueryClient, keys: readonly MutationKey[]): Set<object> {
  return new Set(
    keys.flatMap((mutationKey) =>
      client
        .getMutationCache()
        .findAll({ mutationKey })
        .filter((mutation) => {
          const context = mutation.state.context as WriteContext | undefined
          return context?.phase === 'refreshing' || mutation.state.status !== 'pending'
        }),
    ),
  )
}

/** A read spanning a saved change must finish with a fresh server snapshot. */
export async function readAfterWrites<T>(
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
