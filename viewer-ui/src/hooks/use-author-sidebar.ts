import { useState, type RefObject } from 'react'

import { useDockedSidebar, type DockedSidebar } from '@/hooks/use-docked-sidebar'

type SidebarFocus = 'panel' | 'search'
type SidebarOptions = {
  active: boolean
  docked: boolean
  toggleRef: RefObject<HTMLButtonElement | null>
}

export type MobileSidebar = {
  available: boolean
  isOpen: boolean
  focus: SidebarFocus
  toggleRef: RefObject<HTMLButtonElement | null>
  close: () => void
}

export type AuthorSidebar = {
  layout: DockedSidebar
  mobile: MobileSidebar
  isOpen: boolean
  toggle: () => void
  search: (input: RefObject<HTMLInputElement | null>) => void
}

/** Desktop preferences survive the temporary mobile sheet and tab changes. */
export function useAuthorSidebar(options: SidebarOptions): AuthorSidebar {
  const layout = useDockedSidebar(options)
  const available = options.active && !options.docked
  const [focus, setFocus] = useState<SidebarFocus | null>(null)
  if (!available && focus !== null) setFocus(null)
  const close = (): void => setFocus(null)
  const isOpen = options.docked ? layout.isOpen : available && focus !== null

  return {
    layout,
    mobile: {
      available,
      isOpen: available && focus !== null,
      focus: focus ?? 'panel',
      toggleRef: options.toggleRef,
      close,
    },
    isOpen,
    toggle: () => {
      if (options.docked) layout.toggle()
      else if (available) setFocus((current) => (current === null ? 'panel' : null))
    },
    search: (input) => {
      if (!options.active) return
      if (options.docked) layout.show()
      else if (!isOpen) {
        setFocus('search')
        return
      }
      input.current?.focus()
      input.current?.select()
    },
  }
}
