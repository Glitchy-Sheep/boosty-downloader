import type { MediaPage, MediaPost } from '@/lib/api.gen'
import { savedRow, savedVideo } from '@/test/post-fixtures'

export const savedMediaPost: MediaPost = {
  title: savedRow.title,
  cover_path: savedRow.cover_path,
  access: savedRow.access,
  seen: savedRow.seen,
  favorite: savedRow.favorite,
}

export const savedMediaPage: MediaPage = {
  items: [savedVideo],
  posts: { [savedRow.id]: savedMediaPost },
  counts: { all: 1, images: 0, videos: 1, audio: 0, files: 0 },
  missing: 2,
}
