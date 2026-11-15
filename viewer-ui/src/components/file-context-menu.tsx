import { ContextMenu } from 'radix-ui'
import { useLayoutEffect, useRef, useState, type ReactElement, type SyntheticEvent } from 'react'

import { FileMenuItems } from '@/components/file-actions'
import { useTabActive } from '@/lib/author-tab'
import type { FileAction } from '@/lib/file-action-types'

type FileContextMenuProps = {
  actions: readonly FileAction[]
  enabled: boolean
  active?: boolean
  label: string
  children: ReactElement
}

function isLinkGesture(event: SyntheticEvent): boolean {
  return event.target instanceof Element && event.target.closest('a[href]') !== null
}

/** Links keep the browser menu; the surrounding local file offers its actions. */
export function FileContextMenu({
  actions,
  enabled,
  active: explicitActive,
  label,
  children,
}: FileContextMenuProps) {
  const tabActive = useTabActive()
  const active = explicitActive ?? tabActive
  const available = active && enabled && actions.length > 0
  const [open, setOpen] = useState(false)
  const linkGesture = useRef(false)
  const latestActive = useRef(available)
  if (!available && open) setOpen(false)
  useLayoutEffect(() => {
    latestActive.current = available
    return () => {
      latestActive.current = false
    }
  }, [available])
  if (!available) return children
  return (
    <ContextMenu.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen || !linkGesture.current) setOpen(nextOpen)
      }}
    >
      <ContextMenu.Trigger
        asChild
        data-file-context=""
        style={{ WebkitTouchCallout: 'default' }}
        onContextMenuCapture={(event) => {
          linkGesture.current = isLinkGesture(event)
          if (linkGesture.current) event.stopPropagation()
        }}
        onPointerDownCapture={(event) => {
          linkGesture.current = isLinkGesture(event)
        }}
      >
        {children}
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content
          aria-label={label}
          className="file-action-menu"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          onCloseAutoFocus={(event) => {
            if (!latestActive.current) event.preventDefault()
          }}
        >
          <FileMenuItems actions={actions} kind="context" />
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  )
}
