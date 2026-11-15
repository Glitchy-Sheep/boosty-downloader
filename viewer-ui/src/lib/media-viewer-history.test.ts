import type { ParsedHistoryState } from '@tanstack/history'
import { createMemoryHistory } from '@tanstack/react-router'
import { describe, expect, test } from 'vitest'

import {
  canCloseMediaViewerWithBack,
  closeMediaViewerState,
  mediaViewerScope,
  openMediaViewerState,
  stepMediaViewerState,
} from '@/lib/media-viewer-history'

const scope = mediaViewerScope('studio', { view: 'images', fav: 1 })

describe('fullscreen history entries', () => {
  test('arrows replace one opening entry, Escape consumes it, and Forward reopens the last piece', () => {
    const history = createMemoryHistory({
      initialEntries: ['/', '/a/studio/media?view=images&fav=1'],
    })
    const grid = history.location
    history.push(`${grid.href}&open=first`, openMediaViewerState(grid.state, scope))
    const firstKey = history.location.state.__TSR_key
    history.replace(`${grid.href}&open=third`, stepMediaViewerState(history.location.state, scope))
    expect(history.length).toBe(3)
    expect(history.location.state.__TSR_key).not.toBe(firstKey)
    expect(history.location.state.mediaViewerOrigin?.parentKey).toBe(grid.state.__TSR_key)
    expect(canCloseMediaViewerWithBack(history.location.state, scope)).toBe(true)
    history.back()
    expect(history.location.href).toBe(grid.href)
    history.forward()
    expect(history.location.href).toContain('open=third')
    expect(canCloseMediaViewerWithBack(history.location.state, scope)).toBe(true)
    history.back()
    history.back()
    expect(history.location.href).toBe('/')
    history.destroy()
  })

  test('a direct link and its arrows close by replace without consuming an unrelated page', () => {
    const history = createMemoryHistory({ initialEntries: ['/', '/a/studio/media?open=first'] })
    expect(canCloseMediaViewerWithBack(history.location.state, scope)).toBe(false)
    history.replace(
      '/a/studio/media?open=second',
      stepMediaViewerState(history.location.state, scope),
    )
    expect(canCloseMediaViewerWithBack(history.location.state, scope)).toBe(false)
    history.replace('/a/studio/media', closeMediaViewerState(history.location.state))
    expect(history.location.state.mediaViewerOrigin).toBeUndefined()
    history.back()
    expect(history.location.href).toBe('/')
    history.destroy()
  })

  test('ordinary navigation cannot reuse the previous opening and a new visit gets its own parent', () => {
    const history = createMemoryHistory({ initialEntries: ['/a/studio/media'] })
    const firstParent = history.location.state.__TSR_key
    history.push('/a/studio/media?open=first', openMediaViewerState(history.location.state, scope))
    history.push('/a/studio/p/post')
    expect(canCloseMediaViewerWithBack(history.location.state, scope)).toBe(false)
    history.push('/a/studio/media')
    const nextParent = history.location.state.__TSR_key
    history.push('/a/studio/media?open=last', openMediaViewerState(history.location.state, scope))
    expect(nextParent).not.toBe(firstParent)
    expect(history.location.state.mediaViewerOrigin?.parentKey).toBe(nextParent)
    expect(canCloseMediaViewerWithBack(history.location.state, scope)).toBe(true)
    history.back()
    expect(history.location.state.__TSR_key).toBe(nextParent)
    history.destroy()
  })

  test('foreign authors, filters and history positions discard an inherited opening marker', () => {
    const parent: ParsedHistoryState = { __TSR_key: 'parent', __TSR_index: 3 }
    const opened = { ...openMediaViewerState(parent, scope), __TSR_key: 'child', __TSR_index: 4 }
    for (const other of [
      mediaViewerScope('other', { view: 'images', fav: 1 }),
      mediaViewerScope('studio', {}),
    ]) {
      expect(canCloseMediaViewerWithBack(opened, other)).toBe(false)
      expect(stepMediaViewerState(opened, other).mediaViewerOrigin).toBeUndefined()
    }
    const later = { ...opened, __TSR_index: 5 }
    expect(canCloseMediaViewerWithBack(later, scope)).toBe(false)
    expect(stepMediaViewerState(later, scope).mediaViewerOrigin).toBeUndefined()
    expect(canCloseMediaViewerWithBack({ ...opened, __TSR_index: 3 }, scope)).toBe(false)
  })

  test('only list filters identify the visit, and missing entry keys cannot claim a Back target', () => {
    expect(mediaViewerScope('studio', { view: 'images', fav: 1, open: 'first' })).toBe(scope)
    expect(mediaViewerScope('studio', { fav: 1, view: 'images', open: 'last' })).toBe(scope)
    expect(mediaViewerScope('studio', { view: 'images', fav: 1, unseen: 1 })).not.toBe(scope)
    expect(mediaViewerScope('studio', { view: 'images', fav: 1, order: 'oldest' })).not.toBe(scope)
    expect(openMediaViewerState({ __TSR_index: 0 }, scope).mediaViewerOrigin).toBeUndefined()
    expect(
      openMediaViewerState({ key: 'legacy', __TSR_index: 2 }, scope).mediaViewerOrigin?.parentKey,
    ).toBe('legacy')
  })
})
