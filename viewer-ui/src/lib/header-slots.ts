import { createContext, useContext } from 'react'

type HeaderPlaces = { start: HTMLElement | null; tabs: HTMLElement | null }

/** Author controls share stable positions in the library header. */
export const HeaderSlots = createContext<HeaderPlaces>({ start: null, tabs: null })

export function useHeaderSlots(): HeaderPlaces {
  return useContext(HeaderSlots)
}
