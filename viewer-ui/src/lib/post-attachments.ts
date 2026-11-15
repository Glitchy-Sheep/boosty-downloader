import type { MediaItem } from '@/lib/api.gen'
import { displayFileName, fileNameOnDisk } from '@/lib/file-presentation'
import { mediaPath } from '@/lib/media-paths'

export type PostAttachment = {
  item: MediaItem
  card: HTMLElement
  icon: HTMLElement
  badge: HTMLElement
  metadata: HTMLElement
  actions: HTMLElement
}

/** Keep encoded separators distinct from path boundaries and decode each segment once. */
function attachmentPath(href: string, origin: string): string | null {
  try {
    const url = new URL(href, origin)
    if (url.origin !== origin || url.username || url.password) return null
    return url.pathname.split('/').map(decodeURIComponent).map(encodeURIComponent).join('/')
  } catch {
    return null
  }
}

function generatedSlot(name: string): HTMLElement {
  const slot = document.createElement('span')
  slot.dataset.pageSlot = name
  return slot
}

function createAttachment(item: MediaItem): PostAttachment {
  const card = document.createElement('div')
  card.className = 'attachment'
  card.dataset.fileCard = item.id
  card.dataset.mediaId = item.id
  card.dataset.fileActionContainer = ''
  const name = document.createElement('span')
  name.className = 'file-name attachment-name'
  name.textContent = displayFileName(fileNameOnDisk(item))
  name.title = name.textContent
  const title = document.createElement('span')
  title.className = 'attachment-title'
  const text = document.createElement('span')
  text.className = 'attachment-text'
  const attachment = {
    item,
    card,
    icon: generatedSlot('icon'),
    badge: generatedSlot('badge'),
    metadata: generatedSlot('metadata'),
    actions: generatedSlot('actions'),
  }
  attachment.metadata.className = 'attachment-meta'
  title.append(name, attachment.badge)
  text.append(title, attachment.metadata)
  card.append(attachment.icon, text, attachment.actions)
  return attachment
}

/** Only indexed files in this post gain actions; all other links retain their saved form. */
export function attachPostAttachments(
  root: HTMLElement,
  author: string,
  postId: string,
  media: readonly MediaItem[],
  origin: string,
): { attachments: PostAttachment[]; cleanup: () => void } {
  const knownFiles = new Map(
    media
      .filter((item) => item.kind === 'files' && item.post_id === postId)
      .map((item) => [attachmentPath(mediaPath(author, item.path), origin), item]),
  )
  const attachments: PostAttachment[] = []
  const originals = new Map<HTMLElement, HTMLAnchorElement>()
  for (const link of root.querySelectorAll<HTMLAnchorElement>('a.attachment[href]')) {
    const path = attachmentPath(link.getAttribute('href') ?? '', origin)
    const item = path === null ? undefined : knownFiles.get(path)
    if (!item) continue
    const attachment = createAttachment(item)
    link.replaceWith(attachment.card)
    originals.set(attachment.card, link)
    attachments.push(attachment)
  }
  return {
    attachments,
    cleanup: () => {
      for (const [card, link] of originals) {
        if (root.contains(card)) card.replaceWith(link)
      }
    },
  }
}
