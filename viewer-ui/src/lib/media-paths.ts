import type { MediaItem } from '@/lib/api.gen'

function pathComponent(value: string): string {
  return encodeURIComponent(value).replace(
    /[!'()*]/g,
    (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
  )
}

/** Stored path segments are encoded once, including literal percent signs. */
export function mediaPath(author: string, path: string): string {
  const segments = path.split('/')
  if (
    segments.some((segment) => !segment || segment === '.' || segment === '..') ||
    /[\\\0]/.test(path)
  )
    throw new Error('Media paths must be relative library files.')
  return `/media/${pathComponent(author)}/${segments.map(pathComponent).join('/')}`
}

export function mediaThumbnailPath(author: string, item: MediaItem): string | null {
  if (item.thumb_path) return mediaPath(author, item.thumb_path)
  if (item.kind === 'images') return mediaPath(author, item.path)
  return null
}
