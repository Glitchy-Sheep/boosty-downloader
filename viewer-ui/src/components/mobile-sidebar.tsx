import { X } from 'lucide-react'
import { Dialog } from 'radix-ui'
import { useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react'

import type { AuthorSidebar } from '@/hooks/use-author-sidebar'
import { keyboardLayer } from '@/lib/keyboard-layer'
import { acceptsPostShortcut, postShortcut } from '@/lib/post-shortcuts'

type MobileSidebarProps = {
  controller: AuthorSidebar
  searchInput: RefObject<HTMLInputElement | null>
  children: ReactNode
}

/** A temporary modal sidebar leaves the selected post and its players mounted. */
export function MobileSidebar({ controller, searchInput, children }: MobileSidebarProps) {
  const { mobile } = controller
  const content = useRef<HTMLDivElement>(null)
  const canReturnFocus = useRef(false)
  useLayoutEffect(() => {
    canReturnFocus.current = mobile.available
    return () => {
      canReturnFocus.current = false
    }
  }, [mobile.available])

  return (
    <Dialog.Root
      open={mobile.isOpen}
      onOpenChange={(open) => {
        if (!open) mobile.close()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/40" />
        <Dialog.Content
          ref={content}
          id="author-post-sidebar"
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            if (mobile.focus === 'search') {
              searchInput.current?.focus()
              searchInput.current?.select()
            } else content.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            if (canReturnFocus.current) mobile.toggleRef.current?.focus()
          }}
          onEscapeKeyDown={(event) => {
            const owner = keyboardLayer(event.target)
            if (owner && owner !== content.current) {
              event.preventDefault()
              return
            }
            if (searchInput.current === document.activeElement) event.preventDefault()
          }}
          onKeyDown={(event) => {
            if (!acceptsPostShortcut(event.nativeEvent, document, event.currentTarget)) return
            switch (postShortcut(event.code)) {
              case 'sidebar':
                event.preventDefault()
                if (!event.repeat) mobile.close()
                break
              case 'search':
                event.preventDefault()
                controller.search(searchInput)
            }
          }}
          className="fixed inset-y-0 left-0 z-30 flex w-[min(88vw,400px)] flex-col border-r bg-card text-card-foreground shadow-xl outline-none"
        >
          <div className="flex h-10 shrink-0 items-center justify-between border-b px-4">
            <Dialog.Title className="text-sm font-medium">Posts</Dialog.Title>
            <Dialog.Close
              aria-label="Close sidebar"
              className="grid size-7 place-items-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <X aria-hidden="true" className="size-4" />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
