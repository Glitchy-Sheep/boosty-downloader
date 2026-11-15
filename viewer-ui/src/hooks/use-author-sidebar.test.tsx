import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'

import { useAuthorSidebar } from '@/hooks/use-author-sidebar'
import { loadSidebarLayout, saveSidebarLayout } from '@/lib/sidebar-layout'

afterEach(() => localStorage.clear())

function setup({ active = true, docked = false } = {}) {
  const toggleRef = { current: document.createElement('button') }
  const input = { current: document.createElement('input') }
  document.body.append(toggleRef.current, input.current)
  const hook = renderHook((options) => useAuthorSidebar({ ...options, toggleRef }), {
    initialProps: { active, docked },
  })
  const unmount = (): void => {
    hook.unmount()
    toggleRef.current.remove()
    input.current.remove()
  }
  return { ...hook, input, unmount }
}

test('mobile opening records a focus intent without changing desktop preferences', () => {
  saveSidebarLayout({ width: 520, collapsed: true })
  const hook = setup()
  expect(hook.result.current.isOpen).toBe(false)
  act(() => hook.result.current.toggle())
  expect(hook.result.current.mobile).toMatchObject({ isOpen: true, focus: 'panel' })
  expect(hook.input.current).not.toHaveFocus()
  act(() => hook.result.current.toggle())
  act(() => hook.result.current.search(hook.input))
  expect(hook.result.current.mobile).toMatchObject({ isOpen: true, focus: 'search' })
  expect(hook.input.current).not.toHaveFocus()
  act(() => hook.result.current.search(hook.input))
  expect(hook.input.current).toHaveFocus()
  act(() => hook.result.current.mobile.close())
  expect(hook.result.current.isOpen).toBe(false)
  expect(loadSidebarLayout()).toEqual({ width: 520, collapsed: true })
  hook.unmount()
})

test('docking and leaving Posts close the sheet without reopening it on return', () => {
  const hook = setup()
  act(() => hook.result.current.toggle())
  hook.rerender({ active: true, docked: true })
  expect(hook.result.current.mobile.isOpen).toBe(false)
  expect(hook.result.current.isOpen).toBe(true)
  hook.rerender({ active: true, docked: false })
  expect(hook.result.current.isOpen).toBe(false)
  act(() => hook.result.current.search(hook.input))
  hook.rerender({ active: false, docked: false })
  act(() => {
    hook.result.current.toggle()
    hook.result.current.search(hook.input)
  })
  hook.rerender({ active: true, docked: false })
  expect(hook.result.current.isOpen).toBe(false)
  expect(hook.input.current).not.toHaveFocus()
  hook.unmount()
})

test('desktop actions retain the saved layout and focus search synchronously', () => {
  saveSidebarLayout({ width: 500, collapsed: true })
  const hook = setup({ docked: true })
  act(() => hook.result.current.search(hook.input))
  expect(hook.result.current.isOpen).toBe(true)
  expect(hook.input.current).toHaveFocus()
  expect(loadSidebarLayout()).toEqual({ width: 500, collapsed: false })
  act(() => hook.result.current.toggle())
  expect(hook.result.current.isOpen).toBe(false)
  expect(loadSidebarLayout()).toEqual({ width: 500, collapsed: true })
  hook.unmount()
})
