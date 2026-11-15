import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { Dialog } from 'radix-ui'
import { useEffect, useLayoutEffect, useRef, type KeyboardEvent } from 'react'

import { useTabActive } from '@/lib/author-tab'

export type PostImage = { src: string; alt: string; trigger: HTMLImageElement }
type PostImageViewerProps = {
  images: PostImage[]
  index: number | null
  onShow: (index: number) => void
  onClose: () => void
}

/** The saved images in reading order, including retained images removed by the author. */
export function PostImageViewer({ images, index, onShow, onClose }: PostImageViewerProps) {
  const active = useTabActive()
  const activity = useRef(active)
  useLayoutEffect(() => {
    activity.current = active
  }, [active])
  const image = index === null ? undefined : images[index]
  const content = useRef<HTMLDivElement>(null)
  const lastTrigger = useRef<HTMLImageElement | null>(null)
  const wasOpen = useRef(false)
  useEffect(() => {
    if (image && !wasOpen.current) lastTrigger.current = image.trigger
    wasOpen.current = Boolean(image)
  }, [image])

  const move = (event: KeyboardEvent) => {
    if (index === null || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
    if (event.key === 'ArrowLeft' && index > 0) onShow(index - 1)
    else if (event.key === 'ArrowRight' && index < images.length - 1) onShow(index + 1)
    else return
    event.preventDefault()
  }

  return (
    <Dialog.Root
      open={active && Boolean(image)}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/95" />
        {image && index !== null && (
          <Dialog.Content
            ref={content}
            aria-describedby={undefined}
            onKeyDown={move}
            onOpenAutoFocus={(event) => {
              event.preventDefault()
              content.current?.focus()
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              if (activity.current && lastTrigger.current?.isConnected) lastTrigger.current.focus()
            }}
            className="fixed inset-0 z-50 flex flex-col text-white outline-none"
          >
            <Dialog.Title className="sr-only">Post image viewer</Dialog.Title>
            <div className="flex h-14 shrink-0 items-center gap-4 px-4 md:px-6">
              <span className="shrink-0 text-sm text-white/65 tabular-nums" aria-live="polite">
                {index + 1} / {images.length}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm">{image.alt}</span>
              <Dialog.Close asChild>
                <button
                  type="button"
                  aria-label="Close image viewer"
                  className="grid size-9 place-items-center rounded-lg outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-white"
                >
                  <X aria-hidden="true" className="size-5" />
                </button>
              </Dialog.Close>
            </div>
            <div className="relative flex min-h-0 flex-1 items-center justify-center px-2 pb-4 md:px-16">
              <img
                key={image.src}
                src={image.src}
                alt={image.alt}
                draggable={false}
                className="max-h-full max-w-full object-contain select-none"
              />
              {index > 0 && <ImageStep direction="previous" onClick={() => onShow(index - 1)} />}
              {index < images.length - 1 && (
                <ImageStep direction="next" onClick={() => onShow(index + 1)} />
              )}
            </div>
          </Dialog.Content>
        )}
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function ImageStep({
  direction,
  onClick,
}: {
  direction: 'previous' | 'next'
  onClick: () => void
}) {
  const next = direction === 'next'
  const placement = next ? 'right-2 md:right-4' : 'left-2 md:left-4'
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={next ? 'Next image' : 'Previous image'}
      className={`absolute top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-full bg-black/40 text-white outline-none backdrop-blur hover:bg-black/70 focus-visible:ring-2 focus-visible:ring-white ${placement}`}
    >
      {next ? (
        <ChevronRight aria-hidden="true" className="size-5" />
      ) : (
        <ChevronLeft aria-hidden="true" className="size-5" />
      )}
    </button>
  )
}
