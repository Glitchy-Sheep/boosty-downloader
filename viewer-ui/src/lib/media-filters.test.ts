import { expect, test } from 'vitest'

import {
  MEDIA_VIEWS,
  NO_MEDIA_FILTERS,
  mediaSearchParams,
  parseMediaSearch,
  toMediaFilters,
} from '@/lib/media-filters'
import { parseViewerSearch, stringifyViewerSearch } from '@/lib/url-search'

test('normalizes all media query fields without fullscreen selection', () => {
  expect(parseMediaSearch({})).toEqual(NO_MEDIA_FILTERS)
  expect(toMediaFilters({ open: 'post:image:1' })).toEqual({
    view: 'all',
    order: 'newest',
    unseen: false,
    fav: false,
  })
  expect(mediaSearchParams(NO_MEDIA_FILTERS).toString()).toBe('')
  const search = parseMediaSearch({
    view: 'videos',
    order: 'oldest',
    unseen: '1',
    fav: true,
    open: '001',
  })
  expect(toMediaFilters(search)).toEqual({
    view: 'videos',
    order: 'oldest',
    unseen: true,
    fav: true,
  })
  expect(mediaSearchParams(search).toString()).toBe('view=videos&order=oldest&unseen=1&fav=1')
})

test.each(MEDIA_VIEWS)('keeps the %s media view and clears post-only filters', (view) => {
  const parsed = parseMediaSearch({
    view,
    tag: 'art',
    q: 'text',
    kind: 'files',
    locked: 1,
    incomplete: 1,
  })
  expect(toMediaFilters(parsed).view).toBe(view)
  expect(Object.keys(parsed)).toEqual(Object.keys(NO_MEDIA_FILTERS))
})

test('opaque fullscreen identities survive URL round trips without JSON coercion', () => {
  for (const open of ['001', 'null', 'true', 'post:audio:Шум + 100% !/#']) {
    expect(parseMediaSearch(parseViewerSearch(stringifyViewerSearch({ open }))).open).toBe(open)
  }
  expect(stringifyViewerSearch({ view: 'videos', open: 'id', ...NO_MEDIA_FILTERS })).toBe('')
})

test('rejects malformed, repeated and unrelated media parameters', () => {
  expect(
    parseMediaSearch({
      view: ['images'],
      order: 'latest',
      unseen: ['1'],
      fav: {},
      open: ['a', 'b'],
    }),
  ).toEqual(NO_MEDIA_FILTERS)
  for (const value of [undefined, null, false, 0, -1, '0', 'true', [], {}, NaN]) {
    expect(parseMediaSearch({ unseen: value, fav: value }).unseen).toBeUndefined()
    expect(parseMediaSearch({ unseen: value, fav: value }).fav).toBeUndefined()
  }
  for (const open of [undefined, null, 0, 1, false, '', [], {}])
    expect(parseMediaSearch({ open }).open).toBeUndefined()
})
