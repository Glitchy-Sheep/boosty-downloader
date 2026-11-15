export const SIDEBAR_WIDTH = { default: 360, min: 260, max: 640 } as const
export const POST_PANE_MIN_WIDTH = 400
export const DOCKED_QUERY = '(min-width: 768px)'
export const SIDEBAR_STORAGE_KEY = 'boosty-viewer.sidebar'
export const SIDEBAR_GLIDE_MS = 260

export type SidebarLayout = { width: number; collapsed: boolean }

/** Chosen desktop width, independent of temporary viewport compression. */
export function clampSidebarWidth(width: number): number {
  return Math.min(SIDEBAR_WIDTH.max, Math.max(SIDEBAR_WIDTH.min, width))
}

function parseSidebarLayout(value: unknown): SidebarLayout | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  if (!('width' in value) || !('collapsed' in value)) return null
  if (typeof value.width !== 'number' || !Number.isFinite(value.width)) return null
  if (typeof value.collapsed !== 'boolean') return null
  return { width: clampSidebarWidth(value.width), collapsed: value.collapsed }
}

/** Invalid or unavailable storage leaves the sidebar at its default layout. */
export function loadSidebarLayout(): SidebarLayout {
  try {
    const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY)
    if (stored !== null) {
      const parsed: unknown = JSON.parse(stored)
      const layout = parseSidebarLayout(parsed)
      if (layout) return layout
    }
  } catch {
    // Layout preferences remain optional when browser storage is unavailable.
  }
  return { width: SIDEBAR_WIDTH.default, collapsed: false }
}

export function saveSidebarLayout(layout: SidebarLayout): void {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify(layout))
  } catch {
    // Resizing still works when browser storage is unavailable.
  }
}
