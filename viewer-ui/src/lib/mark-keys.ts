import type { PostMarkKind } from '@/lib/post-marks'

export const markMutationKeys = {
  all: ['marks'] as const,
  author: (author: string) => ['marks', author] as const,
  singles: (author: string) => ['marks', author, 'post'] as const,
  post: (author: string, postId: string) => ['marks', author, 'post', postId] as const,
  single: (author: string, postId: string, kind: PostMarkKind) =>
    ['marks', author, 'post', postId, kind] as const,
  bulk: (author: string) => ['marks', author, 'bulk'] as const,
}
