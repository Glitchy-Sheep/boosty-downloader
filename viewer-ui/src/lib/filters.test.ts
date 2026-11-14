import { describe, expect, it } from 'vitest'

import { filtersSearchParams, hasFilters, KINDS, NO_FILTERS, parseFilters, toPostFilters, type Filters } from '@/lib/filters'
import { parseViewerSearch, stringifyViewerSearch } from '@/lib/url-search'

const allFilters: Filters = {
  q: 'шейдер + <script>', kind: 'videos', unseen: 1, fav: 1,
  tag: '01.0', locked: 1, incomplete: 1, order: 'oldest',
}

describe('post URL filters', () => {
  it('normalizes an empty address into every API default', () => {
    expect(parseFilters({})).toEqual(NO_FILTERS)
    expect(toPostFilters({})).toEqual({
      q: '', kind: null, unseen: false, fav: false, tag: null,
      locked: false, incomplete: false, order: 'newest',
    })
    expect(filtersSearchParams(NO_FILTERS).toString()).toBe('')
    expect(hasFilters(NO_FILTERS)).toBe(false)
    expect(toPostFilters({ tag: '' }).tag).toBeNull()
  })

  it('retains every filter in a copied address and its API request', () => {
    const parsed = parseFilters(parseViewerSearch(stringifyViewerSearch(allFilters)))
    expect(parsed).toEqual(allFilters)
    const params = filtersSearchParams(parsed)
    expect(params.get('q')).toBe('шейдер + <script>')
    expect(params.get('tag')).toBe('01.0')
    expect(params.get('kind')).toBe('videos')
    expect(params.get('order')).toBe('oldest')
    for (const key of ['unseen', 'fav', 'locked', 'incomplete']) expect(params.get(key)).toBe('1')
    expect(toPostFilters(parsed)).toEqual({ ...allFilters, unseen: true, fav: true, locked: true, incomplete: true })
  })

  it.each(KINDS)('accepts the generated media kind %s', kind => {
    expect(parseFilters({ kind }).kind).toBe(kind)
  })

  it.each(['q', 'tag'] as const)('keeps literal %s text without trimming or JSON parsing', key => {
    for (const value of ['001', '1.0', 'null', 'true', 'false', '"foo"', '  art  ', '100% + архив']) {
      expect(parseFilters({ [key]: value })[key]).toBe(value)
    }
    expect(parseFilters({ [key]: 0 })[key]).toBe('0')
    expect(parseFilters({ [key]: 2024 })[key]).toBe('2024')
    expect(parseFilters({ [key]: false })[key]).toBe('false')
  })

  it.each(['unseen', 'fav', 'locked', 'incomplete'] as const)('accepts only enabled flag forms for %s', key => {
    for (const value of [1, '1', true]) expect(parseFilters({ [key]: value })[key]).toBe(1)
    for (const value of [0, '0', false, 'true', -1, 'yes', [], ['1'], {}, null]) {
      expect(parseFilters({ [key]: value })[key]).toBeUndefined()
    }
  })

  it('discards unknown, repeated and structured inputs', () => {
    expect(parseFilters({
      q: ['a', 'b'], tag: { name: 'art' }, kind: 'other', order: 'latest',
      unseen: ['1'], fav: {}, locked: -1, incomplete: 'yes', view: 'images',
    })).toEqual(NO_FILTERS)
    for (const value of [undefined, null, '', NaN, Infinity, -Infinity, Symbol('tag')]) {
      expect(parseFilters({ q: value, tag: value })).toEqual(NO_FILTERS)
    }
  })

  it('clears all retained fields and recognizes each active filter', () => {
    const cleared = { ...allFilters, ...NO_FILTERS }
    expect(Object.keys(cleared)).toHaveLength(8)
    expect(hasFilters(cleared)).toBe(false)
    expect(stringifyViewerSearch(cleared)).toBe('')
    for (const [key, value] of Object.entries(allFilters)) {
      expect(hasFilters(parseFilters({ [key]: value })), key).toBe(true)
    }
  })
})
