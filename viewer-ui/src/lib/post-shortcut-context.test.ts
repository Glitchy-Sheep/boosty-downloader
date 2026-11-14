import { afterEach, expect, test } from 'vitest'

import type { PostRow } from '@/lib/api.gen'
import type { Filters } from '@/lib/filters'
import { readPostShortcutContext } from '@/lib/post-shortcut-context'
import { createQueryClient, postQuery, postsQuery } from '@/lib/queries'
import { stringifyViewerSearch } from '@/lib/url-search'
import { savedPost, savedRow } from '@/test/post-fixtures'

const client = createQueryClient()
const first = { ...savedRow, id: 'first', created_at: '2026-01-03T00:00:00Z' }
const current = { ...savedRow, id: 'current', created_at: '2026-01-02T00:00:00Z' }
const last = { ...savedRow, id: 'last', created_at: '2026-01-01T00:00:00Z' }

afterEach(() => client.clear())

function cacheList(
  rows: PostRow[] = [first, current, last],
  filters: Filters = {},
  author = 'studio',
) {
  const query = postsQuery(author, filters)
  client.setQueryData(query.queryKey, { rows, total: rows.length, months: [] })
  return query
}

function read(pathname = '/a/studio/p/current', filters: Filters = {}) {
  return readPostShortcutContext(
    client,
    { pathname, search: stringifyViewerSearch(filters) },
    'studio',
  )
}

test('uses the exact query list and preserves all eight normalized filters', () => {
  const filters: Filters = {
    q: '001.0 café',
    kind: 'images',
    unseen: 1,
    fav: 1,
    tag: 'null',
    locked: 1,
    incomplete: 1,
    order: 'oldest',
  }
  cacheList([last, current, first], filters)
  expect(read('/a/studio/p/current', filters)).toEqual({
    author: 'studio',
    postId: 'current',
    filters,
    neighbours: { previous: last, next: first },
  })
  expect(read()?.neighbours).toBeNull()
})

test('a retained detail locates a selected post excluded from the current list', () => {
  cacheList([first, last])
  client.setQueryData(postQuery('studio', current.id).queryKey, { ...savedPost, ...current })
  expect(read()?.neighbours).toEqual({ previous: first, next: last })
})

test('a cached detail keeps microsecond ordering when the current row is excluded', () => {
  const early = { ...first, id: '𐀀', created_at: '2026-01-02T00:00:00.000001Z' }
  const late = { ...last, id: 'last', created_at: '2026-01-02T00:00:00.000003Z' }
  cacheList([early, late], { order: 'oldest' })
  client.setQueryData(postQuery('studio', current.id).queryKey, {
    ...savedPost,
    ...current,
    created_at: '2026-01-02T00:00:00.000002Z',
  })
  expect(read('/a/studio/p/current', { order: 'oldest' })?.neighbours).toEqual({
    previous: early,
    next: late,
  })
})

test('excluded rows with equal dates keep Unicode code-point order', () => {
  const before = { ...current, id: 'Z' }
  const after = { ...current, id: '𐀀' }
  const selected = { ...savedPost, ...current, id: '\uE000' }
  cacheList([before, after], { order: 'oldest' })
  client.setQueryData(postQuery('studio', selected.id).queryKey, selected)

  expect(
    read(`/a/studio/p/${encodeURIComponent(selected.id)}`, { order: 'oldest' })?.neighbours,
  ).toEqual({ previous: before, next: after })
})

test('unknown current posts do not invent a navigation position', () => {
  cacheList([first, last])
  expect(read()?.neighbours).toBeNull()
})

test('missing, pending and errored exact lists disable movement without disabling search context', () => {
  expect(read()?.neighbours).toBeNull()
  const query = cacheList()
  const cached = client.getQueryCache().find({ queryKey: query.queryKey })
  if (!cached) throw new Error('Missing cached query')
  cached.setState({ status: 'pending' })
  expect(read()?.neighbours).toBeNull()
  cached.setState({ status: 'error', error: new Error('Unavailable') })
  expect(read()?.neighbours).toBeNull()
  expect(read()?.author).toBe('studio')
})

test('an author index retains search context but has no selected post to move from', () => {
  cacheList()
  expect(read('/a/studio')).toMatchObject({ author: 'studio', postId: null, neighbours: null })
})

test.each([
  '/',
  '/a/other/p/current',
  '/a/studio/media',
  '/a/studio/p/current/extra',
  '/a/%FF/p/current',
])('ignores an inactive or malformed address %s', (path) => {
  cacheList()
  expect(read(path)).toBeNull()
})

test('decodes author and post segments once and accepts a trailing slash', () => {
  const author = 'Студия +'
  const post = { ...current, id: 'encoded # +%' }
  cacheList([first, post, last], {}, author)
  expect(
    readPostShortcutContext(
      client,
      {
        pathname: `/a/${encodeURIComponent(author)}/p/${encodeURIComponent(post.id)}/`,
        search: '',
      },
      author,
    ),
  ).toMatchObject({ author, postId: post.id, neighbours: { previous: first, next: last } })
})
