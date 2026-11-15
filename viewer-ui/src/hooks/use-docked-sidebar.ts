import { useEffect, useRef, useState, type RefObject } from 'react'
import { flushSync } from 'react-dom'
import {
  usePanelRef,
  type Layout,
  type LayoutChangedMeta,
  type PanelImperativeHandle,
} from 'react-resizable-panels'

import {
  clampSidebarWidth,
  loadSidebarLayout,
  saveSidebarLayout,
  SIDEBAR_GLIDE_MS,
  SIDEBAR_WIDTH,
} from '@/lib/sidebar-layout'

type DockedSidebarOptions = {
  active: boolean
  docked: boolean
  toggleRef: RefObject<HTMLButtonElement | null>
}

/** Shared header actions and the persistent panel layout's controller. */
export type DockedSidebar = {
  active: boolean
  docked: boolean
  isOpen: boolean
  initialWidth: number
  toggle: () => void
  /** Expand and remove inert synchronously so the caller can focus search. */
  show: () => void
  reset: () => void
  groupRef: RefObject<HTMLDivElement | null>
  sidebarRef: RefObject<HTMLDivElement | null>
  postRef: RefObject<HTMLDivElement | null>
  panelRef: RefObject<PanelImperativeHandle | null>
  animate: () => void
  stopAnimation: () => void
  restoreLayout: () => void
  fitChosenWidth: () => void
  onLayoutChange: (layout: Layout) => void
  onLayoutChanged: (layout: Layout, meta: LayoutChangedMeta) => void
}

/** Keep the user's desktop preference separate from the currently available space. */
export function useDockedSidebar({
  active,
  docked,
  toggleRef,
}: DockedSidebarOptions): DockedSidebar {
  const panelRef = usePanelRef()
  const groupRef = useRef<HTMLDivElement>(null)
  const sidebarRef = useRef<HTMLDivElement>(null)
  const postRef = useRef<HTMLDivElement>(null)
  const [saved] = useState(loadSidebarLayout)
  const [collapsed, setCollapsed] = useState(saved.collapsed)
  const preference = useRef(saved)
  const restoredDocked = useRef<boolean | null>(null)
  const animationTimer = useRef<number | null>(null)

  const stopAnimation = (): void => {
    if (animationTimer.current !== null) window.clearTimeout(animationTimer.current)
    animationTimer.current = null
    groupRef.current?.removeAttribute('data-animating')
  }

  useEffect(() => stopAnimation, [])

  const animate = (): void => {
    stopAnimation()
    const group = groupRef.current
    if (!active || !docked || !group) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    group.dataset.animating = ''
    animationTimer.current = window.setTimeout(stopAnimation, SIDEBAR_GLIDE_MS)
  }

  const updateCollapsed = (next: boolean): void => {
    if (next && sidebarRef.current?.contains(document.activeElement)) toggleRef.current?.focus()
    preference.current = { ...preference.current, collapsed: next }
    setCollapsed(next)
  }

  const open = (): void => {
    if (!active || !docked) return
    animate()
    flushSync(() => {
      updateCollapsed(false)
      panelRef.current?.resize(preference.current.width)
    })
    saveSidebarLayout(preference.current)
  }

  const toggle = (): void => {
    if (!active || !docked) return
    if (preference.current.collapsed) {
      open()
      return
    }
    animate()
    updateCollapsed(true)
    panelRef.current?.collapse()
    saveSidebarLayout(preference.current)
  }

  const restoreLayout = (): void => {
    stopAnimation()
    restoredDocked.current = null
    const panel = panelRef.current
    const group = groupRef.current
    if (!panel || !group || !active || group.clientWidth === 0) return
    if (docked) {
      panel.resize(preference.current.width)
      if (preference.current.collapsed) panel.collapse()
    } else {
      panel.resize(0)
    }
    restoredDocked.current = docked
  }

  const fitChosenWidth = (): void => {
    if (!active) return
    if (restoredDocked.current !== docked) {
      restoreLayout()
      return
    }
    const panel = panelRef.current
    if (!docked || !panel || preference.current.collapsed) return
    if (panel.getSize().inPixels < preference.current.width - 1)
      panel.resize(preference.current.width)
  }

  const onLayoutChange = (layout: Layout): void => {
    if (!active || !docked || restoredDocked.current !== true) return
    updateCollapsed(layout.sidebar === 0)
  }

  const onLayoutChanged = (layout: Layout, meta: LayoutChangedMeta): void => {
    if (!active || !docked || restoredDocked.current !== true || !meta.isUserInteraction) return
    const percentage = layout.sidebar
    if (percentage === undefined) return
    if (percentage > 0) {
      // Layout callbacks precede the panel DOM update; only the total width is current.
      const total = (sidebarRef.current?.offsetWidth ?? 0) + (postRef.current?.offsetWidth ?? 0)
      if (total <= 0) return
      preference.current = {
        width: clampSidebarWidth(Math.round((percentage / 100) * total)),
        collapsed: false,
      }
    }
    saveSidebarLayout(preference.current)
  }

  return {
    active,
    docked,
    isOpen: docked && !collapsed,
    initialWidth: saved.width,
    toggle,
    show: () => {
      if (preference.current.collapsed) open()
    },
    reset: () => {
      if (!active || !docked) return
      preference.current = { ...preference.current, width: SIDEBAR_WIDTH.default }
      open()
    },
    groupRef,
    sidebarRef,
    postRef,
    panelRef,
    animate,
    stopAnimation,
    restoreLayout,
    fitChosenWidth,
    onLayoutChange,
    onLayoutChanged,
  }
}
