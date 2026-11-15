import { expect, test } from 'vitest'

import { mediaPath, mediaThumbnailPath } from '@/lib/media-paths'
import { savedVideo } from '@/test/post-fixtures'

test('encodes each stored path component once', () => {
  expect(mediaPath('студия', "Пост 100%/Видео !'() #.mp4")).toBe(
    '/media/%D1%81%D1%82%D1%83%D0%B4%D0%B8%D1%8F/%D0%9F%D0%BE%D1%81%D1%82%20100%25/%D0%92%D0%B8%D0%B4%D0%B5%D0%BE%20%21%27%28%29%20%23.mp4',
  )
  expect(mediaPath('studio', 'post/%20 +.png')).toBe('/media/studio/post/%2520%20%2B.png')
})

test.each([
  '',
  '/image.png',
  'post//image.png',
  'post/../image.png',
  './image.png',
  'post\\image.png',
  'post/\0image.png',
])('rejects a nonportable relative media path %s', (path) => {
  expect(() => mediaPath('studio', path)).toThrow('relative library files')
})

test('uses a saved thumbnail, an image original, or no video preview', () => {
  expect(mediaThumbnailPath('studio', { ...savedVideo, thumb_path: 'post/thumb.jpg' })).toBe(
    '/media/studio/post/thumb.jpg',
  )
  expect(
    mediaThumbnailPath('studio', {
      ...savedVideo,
      kind: 'images',
      thumb_path: null,
      path: 'post/photo.png',
    }),
  ).toBe('/media/studio/post/photo.png')
  expect(mediaThumbnailPath('studio', { ...savedVideo, thumb_path: null })).toBeNull()
})
