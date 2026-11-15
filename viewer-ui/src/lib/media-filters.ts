import type { MediaFilters } from '@/lib/api.gen'

export type MediaView = MediaFilters['view']
export const MEDIA_VIEWS = [
  'all',
  'images',
  'videos',
  'audio',
  'files',
] as const satisfies readonly MediaView[]

/** Fullscreen selection belongs to the address, not the media-list query. */
export type MediaSearch = {
  view?: Exclude<MediaView, 'all'> | undefined
  order?: 'oldest' | undefined
  unseen?: 1 | undefined
  fav?: 1 | undefined
  open?: string | undefined
}

export const NO_MEDIA_FILTERS: MediaSearch = {
  view: undefined,
  order: undefined,
  unseen: undefined,
  fav: undefined,
  open: undefined,
}

function flag(value: unknown): 1 | undefined {
  return value === 1 || value === '1' || value === true ? 1 : undefined
}

export function parseMediaSearch(search: Record<string, unknown>): MediaSearch {
  const view = MEDIA_VIEWS.find((candidate) => candidate === search.view)
  return {
    view: view === 'all' ? undefined : view,
    order: search.order === 'oldest' ? 'oldest' : undefined,
    unseen: flag(search.unseen),
    fav: flag(search.fav),
    open: typeof search.open === 'string' && search.open ? search.open : undefined,
  }
}

export function toMediaFilters(search: MediaSearch): MediaFilters {
  return {
    view: search.view ?? 'all',
    order: search.order ?? 'newest',
    unseen: search.unseen === 1,
    fav: search.fav === 1,
  }
}

export function mediaSearchParams(search: MediaSearch): URLSearchParams {
  const params = new URLSearchParams()
  if (search.view) params.set('view', search.view)
  if (search.order) params.set('order', search.order)
  if (search.unseen === 1) params.set('unseen', '1')
  if (search.fav === 1) params.set('fav', '1')
  return params
}
