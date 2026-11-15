import type { ParsedHistoryState } from '@tanstack/history'

import { toMediaFilters, type MediaSearch } from '@/lib/media-filters'

type MediaViewerOrigin = {
  parentKey: string
  parentIndex: number
  scope: string
}

declare module '@tanstack/history' {
  interface HistoryState {
    mediaViewerOrigin?: MediaViewerOrigin | undefined
  }
}

export function mediaViewerScope(author: string, search: MediaSearch): string {
  return JSON.stringify([author, toMediaFilters(search)])
}

/** The opening entry remembers the exact grid visit beneath it. */
export function openMediaViewerState(state: ParsedHistoryState, scope: string) {
  const parentKey = state.__TSR_key ?? state.key
  const mediaViewerOrigin = parentKey
    ? { parentKey, parentIndex: state.__TSR_index, scope }
    : undefined
  return { ...state, mediaViewerOrigin }
}

export function canCloseMediaViewerWithBack(state: ParsedHistoryState, scope: string): boolean {
  const origin = state.mediaViewerOrigin
  return Boolean(
    origin?.parentKey && origin.scope === scope && state.__TSR_index === origin.parentIndex + 1,
  )
}

/** Arrows replace the selected piece inside the same opening entry. */
export function stepMediaViewerState(state: ParsedHistoryState, scope: string) {
  if (canCloseMediaViewerWithBack(state, scope)) return state
  return closeMediaViewerState(state)
}

export function closeMediaViewerState(state: ParsedHistoryState) {
  return { ...state, mediaViewerOrigin: undefined }
}
