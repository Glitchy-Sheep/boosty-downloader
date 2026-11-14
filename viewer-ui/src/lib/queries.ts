import { QueryClient, queryOptions } from '@tanstack/react-query'

import { getAuthors } from '@/lib/api'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: false, refetchOnWindowFocus: false },
    },
  })
}

export function authorsQuery() {
  return queryOptions({
    queryKey: ['authors'],
    queryFn: ({ signal }) => getAuthors(signal),
  })
}
