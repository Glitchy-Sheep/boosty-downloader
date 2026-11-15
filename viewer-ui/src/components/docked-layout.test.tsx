import { act, fireEvent, render, screen } from '@testing-library/react'
import { createRef } from 'react'
import { isCoarsePointer, type PanelImperativeHandle } from 'react-resizable-panels'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { DockedLayout } from '@/components/docked-layout'
import type { DockedSidebar } from '@/hooks/use-docked-sidebar'

vi.mock(import('react-resizable-panels'), async (importOriginal) => ({
  ...(await importOriginal()),
  isCoarsePointer: vi.fn(() => false),
}))

type ObservedResize = {
  observer: ResizeObserver
  callback: ResizeObserverCallback
  elements: Set<Element>
  disconnect: () => void
}

const resizes: ObservedResize[] = []

function geometry(element: Element): DOMRect {
  if (element.hasAttribute('data-group')) return new DOMRect(0, 0, 1000, 700)
  if (element.getAttribute('data-testid') === 'sidebar') return new DOMRect(0, 0, 360, 700)
  if (element.getAttribute('data-testid') === 'post') return new DOMRect(361, 0, 639, 700)
  if (element.getAttribute('role') === 'separator') return new DOMRect(360, 0, 1, 700)
  return new DOMRect()
}

beforeEach(() => {
  resizes.length = 0
  vi.mocked(isCoarsePointer).mockReturnValue(false)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    return geometry(this)
  })
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    return geometry(this).width
  })
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    return geometry(this).height
  })
  vi.spyOn(HTMLElement.prototype, 'offsetLeft', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    return geometry(this).left
  })
  vi.stubGlobal(
    'ResizeObserver',
    class implements ResizeObserver {
      readonly elements = new Set<Element>()
      readonly disconnect = vi.fn()
      constructor(callback: ResizeObserverCallback) {
        resizes.push({
          observer: this,
          callback,
          elements: this.elements,
          disconnect: this.disconnect,
        })
      }
      observe(element: Element): void {
        this.elements.add(element)
      }
      unobserve(element: Element): void {
        this.elements.delete(element)
      }
    },
  )
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function controller(): DockedSidebar {
  return {
    active: true,
    docked: true,
    isOpen: true,
    initialWidth: 360,
    toggle: vi.fn(),
    show: vi.fn(),
    reset: vi.fn(),
    groupRef: createRef<HTMLDivElement>(),
    sidebarRef: createRef<HTMLDivElement>(),
    postRef: createRef<HTMLDivElement>(),
    panelRef: createRef<PanelImperativeHandle>(),
    animate: vi.fn(),
    stopAnimation: vi.fn(),
    restoreLayout: vi.fn(),
    fitChosenWidth: vi.fn(),
    onLayoutChange: vi.fn(),
    onLayoutChanged: vi.fn(),
  }
}

function layout(value: DockedSidebar) {
  return (
    <DockedLayout
      controller={value}
      sidebar={<input aria-label="Search posts" />}
      pane={
        <section aria-label="Selected post">
          <video aria-label="Saved video">
            <track kind="captions" />
          </video>
        </section>
      }
    />
  )
}

test('preserves the exact post and native player elements across both breakpoint directions', () => {
  const state = controller()
  const view = render(layout(state))
  const post = screen.getByRole('region', { name: 'Selected post' })
  const video = screen.getByLabelText('Saved video')
  const group = state.groupRef.current
  expect(state.restoreLayout).toHaveBeenCalledOnce()
  expect(group).toHaveAttribute('data-sidebar-layout', 'docked')
  view.rerender(layout({ ...state, docked: false }))
  expect(screen.getByRole('region', { name: 'Selected post' })).toBe(post)
  expect(screen.getByLabelText('Saved video')).toBe(video)
  expect(screen.queryByLabelText('Search posts')).not.toBeInTheDocument()
  expect(state.groupRef.current).toBe(group)
  expect(group).toHaveAttribute('data-sidebar-layout', 'mobile')
  expect(screen.getByRole('separator', { hidden: true })).toHaveAttribute('hidden')
  expect(screen.getByTestId('sidebar').style.flexGrow).toBe('0')
  expect(screen.getByTestId('post').style.flexGrow).toBe('100')
  view.rerender(layout(state))
  expect(screen.getByRole('region', { name: 'Selected post' })).toBe(post)
  expect(screen.getByLabelText('Saved video')).toBe(video)
  expect(state.restoreLayout).toHaveBeenCalledTimes(3)
  expect(screen.getByRole('separator')).not.toHaveAttribute('hidden')
})

test('makes collapsed content inert and exposes the stable header control target', () => {
  const state = controller()
  const view = render(layout({ ...state, isOpen: false }))
  const content = screen.getByLabelText('Search posts').parentElement
  expect(content).toHaveAttribute('id', 'author-post-sidebar')
  expect(content).toHaveAttribute('inert')
  view.rerender(layout(state))
  expect(content).not.toHaveAttribute('inert')
})

test('resets only inside the active docked edge and never through a portaled overlay', () => {
  const state = controller()
  const view = render(layout(state))
  const edge = screen.getByRole('separator')
  expect(fireEvent.doubleClick(edge, { clientX: 360, clientY: 120 })).toBe(false)
  expect(state.reset).toHaveBeenCalledOnce()
  fireEvent.doubleClick(edge, { clientX: 100, clientY: 120 })
  fireEvent.doubleClick(edge, { clientX: 360, clientY: -1 })
  fireEvent.doubleClick(edge, { clientX: 360, clientY: 701 })
  const overlay = document.createElement('div')
  overlay.setAttribute('role', 'menu')
  document.body.append(overlay)
  fireEvent.doubleClick(overlay, { clientX: 360, clientY: 120 })
  overlay.remove()
  expect(state.reset).toHaveBeenCalledOnce()
  vi.mocked(isCoarsePointer).mockReturnValue(true)
  fireEvent.doubleClick(edge, { clientX: 372, clientY: 120 })
  expect(state.reset).toHaveBeenCalledTimes(2)
  view.rerender(layout({ ...state, active: false }))
  fireEvent.doubleClick(edge, { clientX: 360, clientY: 120 })
  view.rerender(layout({ ...state, docked: false }))
  fireEvent.doubleClick(edge, { clientX: 360, clientY: 120 })
  expect(state.reset).toHaveBeenCalledTimes(2)
  view.unmount()
  fireEvent.doubleClick(document, { clientX: 360, clientY: 120 })
  expect(state.reset).toHaveBeenCalledTimes(2)
})

test('glides resize keys but makes pointer input immediate', () => {
  const state = controller()
  const view = render(layout(state))
  const edge = screen.getByRole('separator')
  fireEvent.keyDown(edge, { key: 'Tab' })
  fireEvent.keyDown(edge, { key: 'Escape' })
  expect(state.animate).not.toHaveBeenCalled()
  for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) fireEvent.keyDown(edge, { key })
  expect(state.animate).toHaveBeenCalledTimes(4)
  fireEvent.pointerDown(screen.getByLabelText('Search posts'))
  expect(state.stopAnimation).toHaveBeenCalledOnce()
  view.unmount()
  fireEvent.keyDown(edge, { key: 'ArrowLeft' })
  expect(state.animate).toHaveBeenCalledTimes(4)
})

test('Enter toggles the chosen pixel width and bypasses the library percentage restoration', () => {
  const state = controller()
  const view = render(layout(state))
  const edge = screen.getByRole('separator')
  const layoutBefore = state.sidebarRef.current?.style.flexGrow
  expect(fireEvent.keyDown(edge, { key: 'Enter' })).toBe(false)
  expect(state.toggle).toHaveBeenCalledOnce()
  expect(state.animate).not.toHaveBeenCalled()
  expect(state.sidebarRef.current?.style.flexGrow).toBe(layoutBefore)
  fireEvent.keyDown(edge, { key: 'Enter', repeat: true })
  expect(state.toggle).toHaveBeenCalledOnce()
  view.rerender(layout({ ...state, active: false }))
  fireEvent.keyDown(edge, { key: 'Enter' })
  view.rerender(layout({ ...state, docked: false }))
  fireEvent.keyDown(edge, { key: 'Enter' })
  expect(state.toggle).toHaveBeenCalledOnce()
})

test('fits after the library resize and cancels pending frames and observers on unmount', () => {
  const state = controller()
  const frames = new Map<number, FrameRequestCallback>()
  let nextFrame = 0
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    frames.set(++nextFrame, callback)
    return nextFrame
  })
  const cancel = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation((id) => {
    frames.delete(id)
  })
  const view = render(layout(state))
  const observed = resizes.find(
    (resize) => resize.elements.size === 1 && resize.elements.has(state.groupRef.current!),
  )
  expect(observed).toBeDefined()
  if (!observed) throw new Error('Missing layout observer')
  act(() => {
    observed.callback([], observed.observer)
    observed.callback([], observed.observer)
  })
  expect(state.fitChosenWidth).not.toHaveBeenCalled()
  expect(frames.size).toBe(1)
  act(() => {
    for (const callback of frames.values()) callback(16)
  })
  expect(state.fitChosenWidth).toHaveBeenCalledOnce()
  act(() => observed.callback([], observed.observer))
  view.unmount()
  expect(observed.disconnect).toHaveBeenCalledOnce()
  expect(cancel).toHaveBeenCalledWith(nextFrame)
  expect(frames.size).toBe(0)
})
