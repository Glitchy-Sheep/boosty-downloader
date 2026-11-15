export const playbackMutationKeys = {
  all: ['playback'] as const,
  author: (author: string) => ['playback', author] as const,
  post: (author: string, postId: string) => ['playback', author, postId] as const,
  media: (author: string, postId: string, mediaId: string) =>
    ['playback', author, postId, mediaId] as const,
}
