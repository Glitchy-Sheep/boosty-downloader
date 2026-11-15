import { describe, expect, it } from 'vitest'

import type { MediaItem } from '@/lib/api.gen'
import { mediaPath } from '@/lib/media-paths'
import { attachPostAttachments } from '@/lib/post-attachments'
import { markHits, unmarkHits } from '@/lib/post-search'
import { savedVideo } from '@/test/post-fixtures'

const file: MediaItem = {
  ...savedVideo,
  id: 'file-id',
  path: 'first-post/урок  100%20.pdf',
  kind: 'files',
  file_type: 'pdf',
  filename: 'different-name',
  title: 'Authored title',
}

function fixture(href: string, media: MediaItem[] = [file], author = 'studio') {
  const root = document.createElement('div')
  const link = document.createElement('a')
  link.className = 'attachment'
  link.href = href
  link.innerHTML = '<span class="attachment-name">Authored title</span>'
  root.append(link)
  return {
    root,
    link,
    ...attachPostAttachments(root, author, file.post_id, media, location.origin),
  }
}

describe('post attachments', () => {
  it.each([
    mediaPath('studio', file.path),
    `${location.origin}${mediaPath('studio', file.path)}`,
    `${mediaPath('studio', file.path)}?download=1#page`,
    mediaPath('studio', file.path).replaceAll('%D', '%d'),
    '/media/studio/first-post/урок%20%20100%2520.pdf',
  ])('matches only the indexed media using normalized URI segments: %s', (href) => {
    const { root, attachments } = fixture(href)
    expect(attachments).toHaveLength(1)
    const [attachment] = attachments
    expect(attachment?.item).toBe(file)
    expect(root.querySelector('a')).toBeNull()
    expect(root.querySelector('.file-name')).toHaveTextContent('урок 100%20.pdf')
    expect(root.querySelector('.file-name')?.textContent).toBe('урок  100%20.pdf')
    expect(root.querySelector('[data-file-card]')).toHaveAttribute('data-media-id', file.id)
  })

  it.each([
    'https://remote.invalid/media/studio/first-post/урок%20%20100%2520.pdf',
    `${location.origin.replace('://', '://someone@')}${mediaPath('studio', file.path)}`,
    mediaPath('other-author', file.path),
    mediaPath('studio', file.path).replace('first-post/', 'first-post%2F'),
    mediaPath('studio', file.path).replace('%2520', '%20'),
    mediaPath('studio', file.path).replace('%2520', '%252520'),
    '/media/studio/first-post/missing.pdf',
    '/media/studio/%broken',
    'http://[invalid',
    'javascript:alert(1)',
  ])('keeps unmatched links without adding actions: %s', (href) => {
    const { root, link, attachments } = fixture(href)
    expect(attachments).toHaveLength(0)
    expect(root.firstChild).toBe(link)
    expect(root.querySelector('[data-page-slot]')).toBeNull()
  })

  it('excludes files from another post and non-file media', () => {
    const { root, link, attachments } = fixture(mediaPath('studio', file.path), [
      { ...file, post_id: 'another-post' },
      { ...file, kind: 'images' },
    ])
    expect(attachments).toEqual([])
    expect(root.firstChild).toBe(link)
  })

  it('cleans the label without changing action identity or search-owned text', () => {
    const item = {
      ...file,
      path: 'first-post/invoice\u202efdp\n  .exe',
      file_type: 'program' as const,
    }
    const { root, attachments } = fixture(mediaPath('studio', item.path), [item])
    const name = root.querySelector('.file-name')!
    expect(name.textContent).toBe('invoicefdp�  .exe')
    expect(attachments[0]?.item.path).toBe(item.path)
    for (const slot of root.querySelectorAll('[data-page-slot]')) slot.textContent = 'generated'
    expect(markHits(root, ['invoice', 'generated'])).toHaveLength(1)
    expect(name.querySelector('mark')).not.toBeNull()
    unmarkHits(root)
    expect(name.textContent).toBe('invoicefdp�  .exe')
    expect(root.querySelector('mark')).toBeNull()
  })

  it('retains native players and body listeners, restores only its own card, and cleans up twice', () => {
    const { root, link, cleanup, attachments } = fixture(mediaPath('studio', file.path))
    const player = document.createElement('video')
    player.currentTime = 42
    root.append(player)
    expect(attachments[0]?.card.isConnected).toBe(false)
    cleanup()
    cleanup()
    expect(root.firstChild).toBe(link)
    expect(root.querySelector('video')).toBe(player)
    expect(player.currentTime).toBe(42)
  })

  it('does not restore stale links over freshly rendered HTML', () => {
    const { root, cleanup } = fixture(mediaPath('studio', file.path))
    root.innerHTML = '<a class="attachment" href="/new.pdf">New attachment</a>'
    const fresh = root.firstChild
    cleanup()
    expect(root.firstChild).toBe(fresh)
    expect(root.textContent).toBe('New attachment')
  })

  it('keeps repeated references separate and tolerates missing hrefs', () => {
    const root = document.createElement('div')
    root.innerHTML = `<a class="attachment" href="${mediaPath('studio', file.path)}">One</a><a class="attachment" href="${mediaPath('studio', file.path)}">Two</a><a class="attachment">Missing</a>`
    const first = attachPostAttachments(root, 'studio', file.post_id, [file], location.origin)
    expect(first.attachments).toHaveLength(2)
    expect(new Set(first.attachments.map(({ card }) => card)).size).toBe(2)
    const second = attachPostAttachments(root, 'studio', file.post_id, [file], location.origin)
    expect(second.attachments).toEqual([])
    second.cleanup()
    expect(root.querySelectorAll('[data-file-card]')).toHaveLength(2)
    first.cleanup()
    expect(root.querySelectorAll('a.attachment')).toHaveLength(3)
  })
})
