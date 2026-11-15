import type { OpenerCapabilities } from '@/lib/api.gen'

function validAuthor(author: string): boolean {
  if (/[\\/:\0]/.test(author)) return false
  const name = author.replace(/[ .]+$/, '').toLowerCase()
  return name !== '' && name !== '.boosty-downloader'
}

function validRelativePath(path: string): boolean {
  if (/[\\\0]/.test(path)) return false
  const parts = path.split('/')
  return parts.every((part, index) => {
    if (!part || part === '.' || part === '..' || /^[a-z]:/i.test(part)) return false
    return index === parts.length - 1 || !part.includes(':')
  })
}

/** Preserve the exact stored components, including Unicode and literal percent signs. */
export function localFilePath(
  capabilities: Pick<OpenerCapabilities, 'root' | 'sep'>,
  author: string,
  path: string,
): string | null {
  const { root, sep } = capabilities
  if (!root || root.includes('\0') || !validAuthor(author) || !validRelativePath(path)) return null
  if (sep === '/' && root.startsWith('/')) {
    return `${root.replace(/\/+$/, '')}/${author}/${path}`
  }
  if (sep === '\\' && /^(?:[a-z]:\\|\\\\[^\\]+\\[^\\]+)/i.test(root)) {
    return `${root.replace(/\\+$/, '')}\\${author}\\${path.replaceAll('/', '\\')}`
  }
  return null
}

// Match viewer/media.py's inline MIME policy; file_type describes appearance only.
const INLINE_SUFFIXES = new Set([
  '.jpg',
  '.jpeg',
  '.png',
  '.gif',
  '.webp',
  '.avif',
  '.bmp',
  '.mp3',
  '.m4a',
  '.aac',
  '.ogg',
  '.oga',
  '.opus',
  '.wav',
  '.flac',
  '.mp4',
  '.m4v',
  '.webm',
  '.mov',
  '.mkv',
  '.pdf',
  '.txt',
  '.md',
  '.csv',
  '.vtt',
])

export function canViewInBrowser(path: string): boolean {
  if (path.includes(':') || !validRelativePath(path)) return false
  const name = path
    .slice(path.lastIndexOf('/') + 1)
    .normalize('NFC')
    .replace(/[ .]+$/, '')
  const dot = name.lastIndexOf('.')
  return dot >= 0 && INLINE_SUFFIXES.has(name.slice(dot).toLowerCase())
}
