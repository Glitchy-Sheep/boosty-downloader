import type { PostFilters } from '@/lib/api.gen'

export type Kind = NonNullable<PostFilters['kind']>
export type Order = PostFilters['order']
export const KINDS = ['videos', 'images', 'files', 'audio'] as const satisfies readonly Kind[]

/** Post filters in the address. Missing values use the API defaults. */
export type Filters = {
  q?: string
  kind?: Kind
  unseen?: 1
  fav?: 1
  tag?: string
  locked?: 1
  incomplete?: 1
  order?: Exclude<Order, 'newest'>
}

function flag(value: unknown): 1 | undefined {
  if (value === 1 || value === true || value === '1') return 1
  return undefined
}

function text(value: unknown): string | undefined {
  if (typeof value === 'string') return value || undefined
  if (typeof value === 'boolean') return String(value)
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return undefined
}

/** Ignore malformed filters and unrelated parameters without coercing objects. */
export function parseFilters(search: Record<string, unknown>): Filters {
  return {
    q: text(search.q),
    kind: KINDS.find(kind => kind === search.kind),
    unseen: flag(search.unseen),
    fav: flag(search.fav),
    tag: text(search.tag),
    locked: flag(search.locked),
    incomplete: flag(search.incomplete),
    order: search.order === 'oldest' ? 'oldest' : undefined,
  }
}

/** Explicit undefined keys clear filters retained by route search inheritance. */
export const NO_FILTERS: Filters = {
  q: undefined,
  kind: undefined,
  unseen: undefined,
  fav: undefined,
  tag: undefined,
  locked: undefined,
  incomplete: undefined,
  order: undefined,
}

export function hasFilters(filters: Filters): boolean {
  return Boolean(filters.q || filters.kind || filters.unseen || filters.fav
    || filters.tag || filters.locked || filters.incomplete || filters.order)
}

/** Supply every generated API field for stable query keys and request behavior. */
export function toPostFilters(filters: Filters): PostFilters {
  return {
    q: filters.q ?? '',
    kind: filters.kind ?? null,
    unseen: filters.unseen === 1,
    fav: filters.fav === 1,
    tag: filters.tag || null,
    locked: filters.locked === 1,
    incomplete: filters.incomplete === 1,
    order: filters.order ?? 'newest',
  }
}

/** API flags are 0/1; omitted fields keep their default values. */
export function filtersSearchParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.q) params.set('q', filters.q)
  if (filters.kind) params.set('kind', filters.kind)
  if (filters.unseen === 1) params.set('unseen', '1')
  if (filters.fav === 1) params.set('fav', '1')
  if (filters.tag) params.set('tag', filters.tag)
  if (filters.locked === 1) params.set('locked', '1')
  if (filters.incomplete === 1) params.set('incomplete', '1')
  if (filters.order) params.set('order', filters.order)
  return params
}
