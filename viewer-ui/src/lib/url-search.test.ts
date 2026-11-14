import { describe, expect, it } from 'vitest'

import { NO_FILTERS, parseFilters } from '@/lib/filters'
import { parseViewerSearch, stringifyViewerSearch } from '@/lib/url-search'

describe('flat viewer search parameters', () => {
  it.each(['1.0', '001', 'null', 'true', 'false', '"foo"', 'шейдер + 100% / ? & #'])('round trips literal text %s', value => {
    expect(parseViewerSearch(stringifyViewerSearch({ q: value, tag: value }))).toEqual({ q: value, tag: value })
  })

  it('decodes spaces, plus signs and percent escapes exactly once', () => {
    expect(parseViewerSearch('?q=a+b%2Bc&tag=%252F')).toEqual({ q: 'a b+c', tag: '%2F' })
    expect(stringifyViewerSearch({ q: 'a b+c', tag: '%2F' })).toBe('?q=a+b%2Bc&tag=%252F')
  })

  it('keeps repeated keys as arrays so filter parsing rejects them', () => {
    const parsed = parseViewerSearch('?q=first&q=second&q=third&kind=files&kind=videos&unseen=1&unseen=0')
    expect(parsed).toEqual({ q: ['first', 'second', 'third'], kind: ['files', 'videos'], unseen: ['1', '0'] })
    expect(parseFilters(parsed)).toEqual(NO_FILTERS)
  })

  it('preserves flat parameters for other viewer routes', () => {
    expect(parseViewerSearch('?view=images&open=piece-1&order=oldest')).toEqual({ view: 'images', open: 'piece-1', order: 'oldest' })
    expect(stringifyViewerSearch({ view: 'images', open: 'piece-1', order: 'oldest' })).toBe('?view=images&open=piece-1&order=oldest')
  })

  it('omits absent and non-scalar values without producing a lone question mark', () => {
    expect(stringifyViewerSearch({ q: undefined, tag: null, a: [], b: {}, c: NaN, d: Infinity })).toBe('')
    expect(stringifyViewerSearch({ q: '', unseen: 1, fav: false })).toBe('?q=&unseen=1&fav=false')
    expect(parseViewerSearch('')).toEqual({})
    expect(parseViewerSearch('?')).toEqual({})
  })

  it('treats object property names as data without changing prototypes', () => {
    const parsed = parseViewerSearch('?__proto__=one&__proto__=two&constructor=value&toString=text')
    expect(Object.getPrototypeOf(parsed)).toBeNull()
    expect(parsed.__proto__).toEqual(['one', 'two'])
    expect(parsed.constructor).toBe('value')
    expect(parsed.toString).toBe('text')
    expect(parseViewerSearch(stringifyViewerSearch(parsed))).toEqual({ constructor: 'value', toString: 'text' })
  })
})
