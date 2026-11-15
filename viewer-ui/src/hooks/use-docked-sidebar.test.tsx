import { act, renderHook } from '@testing-library/react'
import type { PanelImperativeHandle } from 'react-resizable-panels'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { useDockedSidebar } from '@/hooks/use-docked-sidebar'
import { loadSidebarLayout, saveSidebarLayout, SIDEBAR_GLIDE_MS } from '@/lib/sidebar-layout'

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
  localStorage.clear()
})

function mountController({ active = true, docked = true } = {}) {
  const group = document.createElement('div')
  const sidebar = document.createElement('div')
  const post = document.createElement('div')
  const toggle = document.createElement('button')
  const search = document.createElement('input')
  sidebar.append(search)
  group.append(sidebar, post)
  document.body.append(toggle, group)
  const size = { sidebar: 360, post: 640, group: 1000 }
  Object.defineProperty(group, 'clientWidth', { get: () => size.group })
  Object.defineProperty(sidebar, 'offsetWidth', { get: () => size.sidebar })
  Object.defineProperty(post, 'offsetWidth', { get: () => size.post })
  const panel: PanelImperativeHandle = {
    collapse: vi.fn(),
    expand: vi.fn(),
    resize: vi.fn(),
    isCollapsed: vi.fn(() => false),
    getSize: vi.fn(() => ({ asPercentage: 36, inPixels: size.sidebar })),
  }
  const hook = renderHook(
    (options) => useDockedSidebar({ ...options, toggleRef: { current: toggle } }),
    { initialProps: { active, docked } },
  )
  hook.result.current.groupRef.current = group
  hook.result.current.sidebarRef.current = sidebar
  hook.result.current.postRef.current = post
  hook.result.current.panelRef.current = panel
  const unmount = (): void => {
    hook.unmount()
    group.remove()
    toggle.remove()
  }
  return { ...hook, unmount, group, sidebar, post, toggle, search, size, panel }
}

test('restores a saved collapse before accepting desktop layout callbacks', () => {
  saveSidebarLayout({ width: 520, collapsed: true })
  const hook = mountController()
  expect(hook.result.current.initialWidth).toBe(520)
  expect(hook.result.current.isOpen).toBe(false)
  act(() => {
    hook.result.current.onLayoutChange({ sidebar: 52, post: 48 })
    hook.result.current.onLayoutChanged({ sidebar: 52, post: 48 }, { isUserInteraction: true })
    hook.result.current.restoreLayout()
  })
  expect(hook.result.current.isOpen).toBe(false)
  expect(hook.panel.resize).toHaveBeenCalledExactlyOnceWith(520)
  expect(hook.panel.collapse).toHaveBeenCalledOnce()
  expect(loadSidebarLayout()).toEqual({ width: 520, collapsed: true })
  hook.unmount()
})

test('collapsing moves sidebar focus to the toggle and opening is synchronous for search', () => {
  const hook = mountController()
  act(() => hook.result.current.restoreLayout())
  hook.search.focus()
  act(() => hook.result.current.toggle())
  expect(hook.toggle).toHaveFocus()
  expect(hook.result.current.isOpen).toBe(false)
  expect(hook.panel.collapse).toHaveBeenCalledOnce()
  expect(loadSidebarLayout()).toEqual({ width: 360, collapsed: true })
  act(() => {
    hook.result.current.show()
    expect(hook.result.current.isOpen).toBe(true)
    hook.search.focus()
  })
  expect(hook.search).toHaveFocus()
  expect(loadSidebarLayout()).toEqual({ width: 360, collapsed: false })
  const previousResizes = vi.mocked(hook.panel.resize).mock.calls.length
  act(() => hook.result.current.show())
  expect(hook.panel.resize).toHaveBeenCalledTimes(previousResizes)
  hook.unmount()
})

test('toggle expands at the chosen pixels after a collapsed viewport resize', () => {
  saveSidebarLayout({ width: 500, collapsed: true })
  const hook = mountController()
  act(() => hook.result.current.restoreLayout())
  hook.size.group = 1400
  hook.size.sidebar = 0
  hook.size.post = 1400
  act(() => {
    hook.result.current.onLayoutChange({ sidebar: 0, post: 100 })
    hook.result.current.onLayoutChanged({ sidebar: 0, post: 100 }, { isUserInteraction: false })
    hook.result.current.fitChosenWidth()
  })
  hook.toggle.focus()
  act(() => hook.result.current.toggle())
  expect(hook.result.current.isOpen).toBe(true)
  expect(hook.panel.resize).toHaveBeenLastCalledWith(500)
  expect(loadSidebarLayout()).toEqual({ width: 500, collapsed: false })
  expect(hook.toggle).toHaveFocus()
  act(() => hook.result.current.toggle())
  expect(hook.toggle).toHaveFocus()
  hook.unmount()
})

test('persists final user pixels from the layout before the panel DOM has updated', () => {
  const hook = mountController()
  act(() => hook.result.current.restoreLayout())
  act(() => {
    hook.result.current.onLayoutChange({ sidebar: 51, post: 49 })
    hook.result.current.onLayoutChanged({ sidebar: 51, post: 49 }, { isUserInteraction: true })
  })
  expect(hook.size.sidebar).toBe(360)
  expect(loadSidebarLayout()).toEqual({ width: 510, collapsed: false })
  hook.search.focus()
  act(() => {
    hook.result.current.onLayoutChange({ sidebar: 0, post: 100 })
    hook.result.current.onLayoutChanged({ sidebar: 0, post: 100 }, { isUserInteraction: true })
  })
  expect(hook.toggle).toHaveFocus()
  expect(hook.result.current.isOpen).toBe(false)
  expect(loadSidebarLayout()).toEqual({ width: 510, collapsed: true })
  act(() => hook.result.current.reset())
  expect(hook.panel.resize).toHaveBeenLastCalledWith(360)
  expect(hook.result.current.isOpen).toBe(true)
  expect(loadSidebarLayout()).toEqual({ width: 360, collapsed: false })
  hook.unmount()
})

test('restores a chosen width after temporary compression without saving the squeeze', () => {
  saveSidebarLayout({ width: 600, collapsed: false })
  const hook = mountController()
  act(() => hook.result.current.restoreLayout())
  act(() => {
    hook.result.current.onLayoutChange({ sidebar: 36, post: 64 })
    hook.result.current.onLayoutChanged({ sidebar: 36, post: 64 }, { isUserInteraction: false })
    hook.result.current.fitChosenWidth()
  })
  expect(hook.panel.resize).toHaveBeenLastCalledWith(600)
  expect(loadSidebarLayout()).toEqual({ width: 600, collapsed: false })
  hook.size.sidebar = 600
  vi.mocked(hook.panel.resize).mockClear()
  act(() => hook.result.current.fitChosenWidth())
  expect(hook.panel.resize).not.toHaveBeenCalled()
  act(() => hook.result.current.toggle())
  act(() => hook.result.current.fitChosenWidth())
  expect(hook.panel.resize).not.toHaveBeenCalled()
  hook.unmount()
})

test('mobile callbacks cannot change the saved desktop layout or hide the temporary split', () => {
  saveSidebarLayout({ width: 550, collapsed: true })
  const hook = mountController()
  act(() => hook.result.current.restoreLayout())
  hook.rerender({ active: true, docked: false })
  act(() => {
    hook.result.current.restoreLayout()
    hook.result.current.onLayoutChange({ sidebar: 52, post: 48 })
    hook.result.current.onLayoutChanged({ sidebar: 52, post: 48 }, { isUserInteraction: true })
    hook.result.current.fitChosenWidth()
    hook.result.current.toggle()
    hook.result.current.show()
    hook.result.current.reset()
  })
  expect(hook.result.current.isOpen).toBe(true)
  expect(hook.panel.resize).toHaveBeenLastCalledWith('52%')
  expect(loadSidebarLayout()).toEqual({ width: 550, collapsed: true })
  hook.rerender({ active: true, docked: true })
  act(() => {
    hook.result.current.onLayoutChange({ sidebar: 52, post: 48 })
    hook.result.current.onLayoutChanged({ sidebar: 52, post: 48 }, { isUserInteraction: true })
    hook.result.current.restoreLayout()
  })
  expect(hook.panel.resize).toHaveBeenLastCalledWith(550)
  expect(hook.panel.collapse).toHaveBeenCalledTimes(2)
  expect(hook.result.current.isOpen).toBe(false)
  hook.unmount()
})

test('inactive panes ignore controls, layout events and deferred resize restoration', () => {
  saveSidebarLayout({ width: 500, collapsed: true })
  const hook = mountController({ active: false })
  act(() => {
    hook.result.current.toggle()
    hook.result.current.show()
    hook.result.current.reset()
    hook.result.current.animate()
    hook.result.current.restoreLayout()
    hook.result.current.fitChosenWidth()
    hook.result.current.onLayoutChange({ sidebar: 45, post: 55 })
    hook.result.current.onLayoutChanged({ sidebar: 45, post: 55 }, { isUserInteraction: true })
  })
  expect(hook.panel.resize).not.toHaveBeenCalled()
  expect(hook.panel.collapse).not.toHaveBeenCalled()
  expect(hook.group).not.toHaveAttribute('data-animating')
  expect(loadSidebarLayout()).toEqual({ width: 500, collapsed: true })
  hook.rerender({ active: true, docked: true })
  act(() => hook.result.current.fitChosenWidth())
  expect(hook.panel.resize).toHaveBeenLastCalledWith(500)
  hook.unmount()
})

test('glides last 260ms, restart cleanly and stop for pointer movement or unmount', () => {
  const hook = mountController()
  act(() => hook.result.current.animate())
  expect(hook.group).toHaveAttribute('data-animating')
  act(() => {
    vi.advanceTimersByTime(200)
  })
  act(() => hook.result.current.animate())
  act(() => {
    vi.advanceTimersByTime(200)
  })
  expect(hook.group).toHaveAttribute('data-animating')
  act(() => {
    vi.advanceTimersByTime(SIDEBAR_GLIDE_MS - 200)
  })
  expect(hook.group).not.toHaveAttribute('data-animating')
  act(() => hook.result.current.animate())
  act(() => hook.result.current.stopAnimation())
  expect(hook.group).not.toHaveAttribute('data-animating')
  expect(vi.getTimerCount()).toBe(0)
  act(() => hook.result.current.animate())
  hook.unmount()
  expect(vi.getTimerCount()).toBe(0)
})

test('reduced motion and missing layout elements never start a glide', () => {
  const hook = mountController()
  const media = window.matchMedia('unused')
  Object.defineProperty(media, 'matches', { value: true })
  vi.spyOn(window, 'matchMedia').mockReturnValue(media)
  act(() => hook.result.current.animate())
  expect(hook.group).not.toHaveAttribute('data-animating')
  expect(vi.getTimerCount()).toBe(0)
  hook.result.current.groupRef.current = null
  act(() => hook.result.current.animate())
  expect(vi.getTimerCount()).toBe(0)
  act(() => hook.result.current.restoreLayout())
  hook.result.current.panelRef.current = null
  act(() => hook.result.current.restoreLayout())
  hook.unmount()
})

test('waits for a hidden group to become measurable before restoring it', () => {
  const hook = mountController()
  hook.size.group = 0
  act(() => hook.result.current.restoreLayout())
  expect(hook.panel.resize).not.toHaveBeenCalled()
  hook.size.group = 1000
  act(() => hook.result.current.fitChosenWidth())
  expect(hook.panel.resize).toHaveBeenCalledExactlyOnceWith(360)
  hook.result.current.panelRef.current = null
  act(() => hook.result.current.fitChosenWidth())
  hook.unmount()
})

test('ignores incomplete or unmeasurable user layouts', () => {
  saveSidebarLayout({ width: 500, collapsed: false })
  const hook = mountController()
  act(() => hook.result.current.restoreLayout())
  act(() => hook.result.current.onLayoutChanged({}, { isUserInteraction: true }))
  hook.result.current.sidebarRef.current = null
  hook.result.current.postRef.current = null
  act(() =>
    hook.result.current.onLayoutChanged({ sidebar: 40, post: 60 }, { isUserInteraction: true }),
  )
  expect(loadSidebarLayout()).toEqual({ width: 500, collapsed: false })
  hook.unmount()
})
