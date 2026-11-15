import type { MediaItem } from '@/lib/api.gen'

/** Decode each segment once so encoded slashes cannot become path separators. */
function mediaSegments(source: string, origin: string): string[] | null {
  try {
    const url = new URL(source, origin)
    if (url.origin !== origin || url.username || url.password) return null
    return url.pathname.split('/').map(decodeURIComponent)
  } catch {
    return null
  }
}

export function findPlaybackMedia(
  source: string,
  author: string,
  postId: string,
  media: readonly MediaItem[],
  origin: string,
): MediaItem | undefined {
  const segments = mediaSegments(source, origin)
  if (!segments || segments[0] !== '' || segments[1] !== 'media' || segments[2] !== author)
    return undefined
  return media.find((item) => {
    if (item.post_id !== postId || (item.kind !== 'videos' && item.kind !== 'audio')) return false
    const expected = item.path.split('/')
    return (
      segments.length === expected.length + 3 &&
      expected.every((part, index) => part === segments[index + 3])
    )
  })
}

export function playerSource(element: HTMLMediaElement): string {
  return (
    element.currentSrc ||
    element.getAttribute('src') ||
    element.querySelector('source')?.getAttribute('src') ||
    ''
  )
}
