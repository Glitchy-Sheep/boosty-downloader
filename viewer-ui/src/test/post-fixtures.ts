import type { Author, MediaItem, PostDetail, PostList, PostRow } from '@/lib/api.gen'

export const savedAuthor: Author = {
  name: 'studio',
  title: 'Studio',
  description: '',
  avatar_url: null,
  cover_url: null,
  posts: 2,
  unseen: 2,
  locked: 0,
  favorites: 1,
  storage: { videos: 100, images: 0, audio: 0, files: 0 },
}

export const savedRow: PostRow = {
  id: 'first-post',
  title: 'Saved post',
  created_at: '2026-01-02T00:00:00Z',
  access: 'open',
  counts: { videos: 1, images: 0, files: 0, audio: 0 },
  cover_path: null,
  seen: false,
  favorite: true,
  updated: false,
  missing_media: 0,
  tier: null,
  match: null,
}

export const savedVideo: MediaItem = {
  id: 'opaque-video',
  post_id: savedRow.id,
  path: 'first-post/video.mp4',
  kind: 'videos',
  file_type: 'video',
  filename: 'video.mp4',
  title: 'Saved video',
  artist: null,
  created_at: savedRow.created_at,
  duration_s: 100,
  position_s: 20,
  finished: false,
  size: 100,
  width: 160,
  height: 90,
  thumb_path: null,
  removed: false,
}

export const savedPost: PostDetail = {
  ...savedRow,
  body_html: '<p>Retained text</p>',
  boosty_url: 'https://boosty.to/studio/posts/first-post',
  has_folder: true,
  media: [savedVideo],
  tags: ['tag'],
  post_price_rub: null,
  tier_price_rub: null,
}

export const savedList: PostList = {
  rows: [savedRow],
  months: [{ month: '2026-01', count: 1 }],
  total: 1,
}
