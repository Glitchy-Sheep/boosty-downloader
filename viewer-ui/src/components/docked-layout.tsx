import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { isCoarsePointer } from 'react-resizable-panels'

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import type { DockedSidebar } from '@/hooks/use-docked-sidebar'
import { POST_PANE_MIN_WIDTH, SIDEBAR_WIDTH } from '@/lib/sidebar-layout'

const EDGE_GRAB = { fine: 12, coarse: 28 }
const RESIZE_KEYS = new Set(['ArrowLeft', 'ArrowRight', 'Home', 'End'])

type DockedLayoutProps = {
  controller: DockedSidebar
  sidebar: ReactNode
  pane: ReactNode
}

/** Preserve the post and its native players while the sidebar changes placement. */
export function DockedLayout({ controller, sidebar, pane }: DockedLayoutProps) {
  const edgeRef = useRef<HTMLDivElement>(null)
  const { docked, active, groupRef } = controller
  const restoreLayout = useEffectEvent(() => controller.restoreLayout())

  useLayoutEffect(() => restoreLayout(), [docked, active])

  const fitChosenWidth = useEffectEvent(() => controller.fitChosenWidth())
  useEffect(() => {
    const group = groupRef.current!
    let frame = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      // Restore chosen pixels after the group has fitted its constraints to the viewport.
      frame = requestAnimationFrame(() => fitChosenWidth())
    })
    observer.observe(group)
    return () => {
      observer.disconnect()
      cancelAnimationFrame(frame)
    }
  }, [groupRef])

  const onDoubleClick = useEffectEvent((event: MouseEvent) => {
    const group = groupRef.current
    const edge = edgeRef.current?.getBoundingClientRect()
    if (!active || !docked || !group || !edge || edge.height <= 0) return
    // Portaled dialogs and menus do not belong to the sidebar's resize edge.
    if (!event.composedPath().includes(group)) return
    const reach = (isCoarsePointer() ? EDGE_GRAB.coarse : EDGE_GRAB.fine) / 2
    const center = edge.left + edge.width / 2
    if (Math.abs(event.clientX - center) > reach) return
    if (event.clientY < edge.top || event.clientY > edge.bottom) return
    event.preventDefault()
    controller.reset()
  })
  useEffect(() => {
    const listener = (event: MouseEvent): void => onDoubleClick(event)
    document.addEventListener('dblclick', listener, true)
    return () => document.removeEventListener('dblclick', listener, true)
  }, [])

  const onResizeKey = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (!active || !docked) return
    if (event.key === 'Enter') {
      event.preventDefault()
      if (!event.repeat) controller.toggle()
      return
    }
    if (RESIZE_KEYS.has(event.key)) controller.animate()
  }

  return (
    <ResizablePanelGroup
      className="docked-layout"
      data-sidebar-layout={docked ? 'docked' : 'mobile'}
      orientation="horizontal"
      disabled={!docked || !active}
      elementRef={groupRef}
      resizeTargetMinimumSize={EDGE_GRAB}
      onLayoutChange={controller.onLayoutChange}
      onLayoutChanged={controller.onLayoutChanged}
      onPointerDownCapture={controller.stopAnimation}
    >
      <ResizablePanel
        id="sidebar"
        className="docked-layout-panel"
        style={{ overflowX: 'hidden' }}
        elementRef={controller.sidebarRef}
        panelRef={controller.panelRef}
        defaultSize={docked ? controller.initialWidth : 0}
        minSize={docked ? SIDEBAR_WIDTH.min : 0}
        maxSize={docked ? SIDEBAR_WIDTH.max : 0}
        collapsible={docked}
        collapsedSize={0}
        groupResizeBehavior="preserve-pixel-size"
      >
        {docked && (
          <div
            id="author-post-sidebar"
            inert={!controller.isOpen}
            className="h-full"
            style={{ '--sidebar-min-width': `${SIDEBAR_WIDTH.min}px` } as CSSProperties}
          >
            {sidebar}
          </div>
        )}
      </ResizablePanel>
      <ResizableHandle
        disableDoubleClick
        disabled={!docked || !active}
        hidden={!docked}
        elementRef={edgeRef}
        aria-label="Sidebar width"
        title="Drag to resize, double-click to reset"
        onKeyDownCapture={onResizeKey}
      />
      <ResizablePanel
        id="post"
        className="docked-layout-panel"
        elementRef={controller.postRef}
        minSize={docked ? POST_PANE_MIN_WIDTH : 0}
      >
        {pane}
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}
