import type { QueryClient } from '@tanstack/react-query'

import { markMutationKeys } from '@/lib/mark-keys'
import type { PostMarkContext, PostMarkRequest } from '@/lib/post-marks'

/** The single-mark key namespace contains only these typed mutation requests. */
export function pendingPostMarks(client: QueryClient, author: string): PostMarkRequest[] {
  return client
    .getMutationCache()
    .findAll({
      mutationKey: markMutationKeys.singles(author),
      status: 'pending',
    })
    .flatMap((mutation) => {
      const context = mutation.state.context as PostMarkContext | undefined
      const request = mutation.state.variables as PostMarkRequest | undefined
      return request && context?.phase !== 'refreshing' ? [request] : []
    })
}
