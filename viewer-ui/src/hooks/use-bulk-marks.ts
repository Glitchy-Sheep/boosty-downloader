import {
  useIsMutating,
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { getMarksProgress, setSeenMany } from '@/lib/api'
import type { BulkMarksResult, PostFilters } from '@/lib/api.gen'
import { markMutationKeys } from '@/lib/mark-keys'
import type { MarkWriteContext } from '@/lib/mark-reads'
import { authorQuery, authorsQuery } from '@/lib/queries'

export type BulkMarkSelection = {
  author: string
  filters: PostFilters
  seen: boolean
  changeCount: number
}

type BulkMarkOperation = {
  id: number
  selection: BulkMarkSelection
  status: 'idle' | 'pending' | 'success' | 'error'
  count: number | null
  error: string | null
}

const PROGRESS_INTERVAL_MS = 250

function authorQueries(author: string) {
  return [
    ['post', author],
    ['posts', author],
    ['media', author],
    authorQuery(author).queryKey,
    authorsQuery().queryKey,
  ]
}

async function refreshMarks(client: QueryClient, author: string): Promise<void> {
  await Promise.all(authorQueries(author).map((queryKey) => client.invalidateQueries({ queryKey })))
}

/** The mutation outlives its dialog; only its POST result establishes completion. */
export function useBulkMarks(author: string) {
  const client = useQueryClient()
  const mutationKey = markMutationKeys.bulk(author)
  const operations = useMutationState({
    filters: { mutationKey, exact: true },
    select: (mutation): BulkMarkOperation | null => {
      const selection = mutation.state.variables as BulkMarkSelection | undefined
      const result = mutation.state.data as BulkMarksResult | undefined
      if (!selection) return null
      return {
        id: mutation.mutationId,
        selection,
        status: mutation.state.status,
        count: result?.count ?? null,
        error: mutation.state.error?.message ?? null,
      }
    },
  })
  const operation = operations.at(-1) ?? null
  const pending = operation?.status === 'pending'
  const blocked = useIsMutating({ mutationKey: markMutationKeys.author(author) }) > 0
  const progress = useQuery({
    queryKey: ['bulk-mark-progress', author, operation?.id ?? null],
    queryFn: ({ signal }) => getMarksProgress(author, signal),
    enabled: pending,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchInterval: pending ? PROGRESS_INTERVAL_MS : false,
  })
  const mutation = useMutation({
    mutationKey,
    mutationFn: (selection: BulkMarkSelection) =>
      setSeenMany(selection.author, { filters: selection.filters, seen: selection.seen }),
    onMutate: (): MarkWriteContext => ({ phase: 'writing' }),
    onSettled: async (_data, _error, selection, context) => {
      if (context) context.phase = 'refreshing'
      await refreshMarks(client, selection.author)
    },
  })

  const start = (selection: BulkMarkSelection): boolean => {
    if (selection.author !== author) return false
    if (client.isMutating({ mutationKey: markMutationKeys.author(author) })) return false
    mutation.mutate({ ...selection, filters: { ...selection.filters } })
    return true
  }

  return {
    start,
    blocked,
    pending,
    operation,
    progress: progress.data,
    progressError: progress.error,
  }
}
