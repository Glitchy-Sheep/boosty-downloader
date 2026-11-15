import { ChevronDown, ChevronUp, Search, X } from 'lucide-react'
import { memo, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react'

import { FileCard } from '@/components/file-card'
import { PostImageViewer, type PostImage } from '@/components/post-image-viewer'
import { usePostAttachments } from '@/hooks/use-post-attachments'
import { usePostPlayback, type SavePosition } from '@/hooks/use-post-playback'
import type { MediaItem } from '@/lib/api.gen'
import { useTabActive } from '@/lib/author-tab'
import { postNavigation, preparePostLinks } from '@/lib/post-body-links'
import { markHits, searchWords, unmarkHits, type SearchHit } from '@/lib/post-search'

type PostBodyProps = {
  author: string
  postId: string
  html: string
  media: MediaItem[]
  query: string | undefined
  onClearSearch: () => void
  savePosition: SavePosition
  onNavigate: (href: string) => void
}

/** Search and playback decorate the saved HTML without replacing its player elements. */
export function PostBody({
  author,
  postId,
  html,
  media,
  query,
  onClearSearch,
  savePosition,
  onNavigate,
}: PostBodyProps) {
  const active = useTabActive()
  const rootRef = useRef<HTMLDivElement>(null)
  const [search, setSearch] = useState<{ revision: number; hits: SearchHit[] }>({
    revision: 0,
    hits: [],
  })
  const [images, setImages] = useState<PostImage[]>([])
  const [imageIndex, setImageIndex] = useState<number | null>(null)

  if (!active && imageIndex !== null) setImageIndex(null)

  const { attachments, inventory } = usePostAttachments({ rootRef, author, postId, html, media })

  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return
    preparePostLinks(root)
    const gallery = Array.from(root.querySelectorAll<HTMLImageElement>('img'))
      .filter((image) => !image.closest('video, audio, a, button'))
      .map((image, index) => ({
        src: image.src,
        alt: image.alt.trim() || `Image ${index + 1}`,
        trigger: image,
      }))
    setImages(gallery)
    setImageIndex(null)
    for (const image of gallery) {
      image.trigger.tabIndex = 0
      image.trigger.setAttribute('role', 'button')
      image.trigger.setAttribute('aria-haspopup', 'dialog')
      image.trigger.setAttribute('aria-label', `Open image: ${image.alt}`)
    }
    const open = (target: EventTarget | null) => {
      const index = gallery.findIndex((image) => image.trigger === target)
      if (index < 0) return false
      setImageIndex(index)
      return true
    }
    const click = (event: MouseEvent) => {
      if (event.button || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      if (open(event.target)) event.preventDefault()
    }
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== ' ') return
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      if (open(event.target)) event.preventDefault()
    }
    root.addEventListener('click', click)
    root.addEventListener('keydown', key)
    return () => {
      root.removeEventListener('click', click)
      root.removeEventListener('keydown', key)
    }
  }, [html, author, postId])

  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return
    const hits = markHits(root, searchWords(query))
    setSearch((previous) => ({ revision: previous.revision + 1, hits }))
    return () => unmarkHits(root)
  }, [html, query, author, postId, inventory])

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const click = (event: MouseEvent) => {
      const href = postNavigation(event)
      if (href === null) return
      event.preventDefault()
      onNavigate(href)
    }
    root.addEventListener('click', click)
    return () => root.removeEventListener('click', click)
  }, [html, onNavigate])

  usePostPlayback({ rootRef, author, postId, html, media, savePosition })

  return (
    <>
      {searchWords(query).length > 0 && (
        <HitsBar key={search.revision} hits={search.hits} onClear={onClearSearch} />
      )}
      {!html.trim() && <p className="text-muted-foreground">This post has no text or media.</p>}
      <SavedHtml html={html} rootRef={rootRef} />
      {attachments.map((attachment, index) => (
        <FileCard
          key={JSON.stringify([author, postId, attachment.item.id, index])}
          author={author}
          attachment={attachment}
        />
      ))}
      <PostImageViewer
        images={images}
        index={imageIndex}
        onShow={setImageIndex}
        onClose={() => setImageIndex(null)}
      />
    </>
  )
}

const SavedHtml = memo(function SavedHtml({
  html,
  rootRef,
}: {
  html: string
  rootRef: RefObject<HTMLDivElement | null>
}) {
  return <div ref={rootRef} className="post-body" dangerouslySetInnerHTML={{ __html: html }} />
})

function HitsBar({ hits, onClear }: { hits: SearchHit[]; onClear: () => void }) {
  const [index, setIndex] = useState(0)
  useEffect(() => {
    const current = hits[index]
    if (!current) return
    for (const mark of current.marks) mark.setAttribute('data-current', '')
    current.marks[0]?.scrollIntoView({ block: 'center' })
    return () => {
      for (const mark of current.marks) mark.removeAttribute('data-current')
    }
  }, [hits, index])
  const label = hits.length
    ? `Match ${index + 1} of ${hits.length} in the text`
    : 'No matches in the text'
  const buttonClass =
    'grid size-8 shrink-0 place-items-center rounded-md outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-35'
  return (
    <div
      role="search"
      aria-label="Search in this post"
      className="sticky top-2 z-20 mb-5 flex items-center gap-2 rounded-lg border bg-popover/95 px-3 py-1.5 text-[12.5px] text-muted-foreground shadow-sm backdrop-blur"
    >
      <Search aria-hidden="true" className="size-3.5 shrink-0" />
      <span aria-live="polite" className="tabular-nums">
        {label}
      </span>
      <div className="ml-auto flex items-center">
        <button
          type="button"
          aria-label="Previous match"
          disabled={index <= 0}
          onClick={() => setIndex(index - 1)}
          className={buttonClass}
        >
          <ChevronUp aria-hidden="true" className="size-4" />
        </button>
        <button
          type="button"
          aria-label="Next match"
          disabled={index >= hits.length - 1}
          onClick={() => setIndex(index + 1)}
          className={buttonClass}
        >
          <ChevronDown aria-hidden="true" className="size-4" />
        </button>
        <button
          type="button"
          aria-label="Clear search in this post"
          onClick={onClear}
          className={buttonClass}
        >
          <X aria-hidden="true" className="size-3.5" />
        </button>
      </div>
    </div>
  )
}
