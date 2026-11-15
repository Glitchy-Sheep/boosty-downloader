import { expect, test } from 'vitest'

import { canViewInBrowser, localFilePath } from '@/lib/local-file-path'

test('copies stored paths without display cleanup, normalization or percent decoding', () => {
  const author = 'автор  %2F'
  const path = 'post/e\u0301  %2520\u202efile.pdf'
  expect(localFilePath({ root: '/library/', sep: '/' }, author, path)).toBe(
    `/library/${author}/${path}`,
  )
  expect(localFilePath({ root: '/', sep: '/' }, author, path)).toBe(`/${author}/${path}`)
  expect(localFilePath({ root: 'C:\\Library\\', sep: '\\' }, author, path)).toBe(
    `C:\\Library\\${author}\\${path.replaceAll('/', '\\')}`,
  )
  expect(localFilePath({ root: '\\\\server\\share', sep: '\\' }, 'author', 'post/file')).toBe(
    '\\\\server\\share\\author\\post\\file',
  )
  expect(localFilePath({ root: '/library', sep: '/' }, 'author', 'post/name:part.txt')).toBe(
    '/library/author/post/name:part.txt',
  )
})

test.each([
  '',
  '.',
  '..',
  '...',
  ' ',
  'author/name',
  'author\\name',
  'author:name',
  'author\0name',
  '.BOOSTY-DOWNLOADER. ',
])('rejects invalid author %j', (author) => {
  expect(localFilePath({ root: '/library', sep: '/' }, author, 'post/file.pdf')).toBeNull()
})

test.each([
  '',
  '/file.pdf',
  'post//file',
  'post/./file',
  'post/../file',
  '../file',
  'post/file\\name',
  'post/file\0name',
  'post/C:file',
  'C:/file',
  'post:stream/file',
])('rejects invalid relative path %j', (path) => {
  expect(localFilePath({ root: '/library', sep: '/' }, 'author', path)).toBeNull()
})

test.each([
  { root: null, sep: '/' },
  { root: '', sep: '/' },
  { root: '/bad\0root', sep: '/' },
  { root: 'relative', sep: '/' },
  { root: '/library', sep: '?' },
  { root: 'C:relative', sep: '\\' },
])('does not invent a root or separator: %j', (capabilities) => {
  expect(localFilePath(capabilities, 'author', 'post/file.pdf')).toBeNull()
})

test.each([
  'jpg',
  'jpeg',
  'png',
  'gif',
  'webp',
  'avif',
  'bmp',
  'mp3',
  'm4a',
  'aac',
  'ogg',
  'oga',
  'opus',
  'wav',
  'flac',
  'mp4',
  'm4v',
  'webm',
  'mov',
  'mkv',
  'pdf',
  'txt',
  'md',
  'csv',
  'vtt',
])('offers browser View for the backend inline suffix %s', (suffix) => {
  expect(canViewInBrowser(`e\u0301/archive/name.${suffix.toUpperCase()} . `)).toBe(true)
  expect(canViewInBrowser(`post/.${suffix}`)).toBe(true)
})

test.each([
  'post/file.svg',
  'post/file.html',
  'post/file.xhtml',
  'post/file.json',
  'post/file.heic',
  'post/file.exe',
  'post/name.pdf.exe',
  'post/no-suffix',
  'post/name:part.pdf',
  'post:stream/name.pdf',
  '../file.pdf',
  'post/file\\name.pdf',
])('does not mistake a display category for safe browser content: %s', (path) => {
  expect(canViewInBrowser(path)).toBe(false)
})
