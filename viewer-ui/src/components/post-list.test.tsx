import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render as renderUi, screen, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { PostList } from '@/components/post-list'
import { createQueryClient } from '@/lib/queries'
import { savedRow } from '@/test/post-fixtures'

const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')

function render(ui: ReactElement) {
  const client = createQueryClient()
  return renderUi(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(240)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(360)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(240)
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    const content = this.firstElementChild
    if (!(content instanceof HTMLElement)) return 0
    const formula = /^calc\(100% \+ (?<offset>[\d.]+)px\)$/.exec(content.style.height)?.groups
    if (formula)
      return Math.max(
        Number.parseFloat(content.style.minHeight),
        Number(formula.offset) + this.clientHeight,
      )
    return Number.parseFloat(content.style.height) || 0
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value(this: HTMLElement, options: ScrollToOptions): void {
      this.scrollTop = Math.max(
        0,
        Math.min(options.top ?? this.scrollTop, this.scrollHeight - this.clientHeight),
      )
      this.dispatchEvent(new Event('scroll'))
    },
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, 'scrollTo', originalScrollTo)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
})

const posts = Array.from({ length: 8 }, (_, index) => 2026 - index).flatMap((year) =>
  ['11', '03'].flatMap((month) =>
    [20, 15, 10, 5].map((day) => ({
      ...savedRow,
      id: `${year}-${month}-${day}`,
      title: `Post ${year}-${month}-${day}`,
      created_at: `${year}-${month}-${String(day).padStart(2, '0')}T00:00:00Z`,
    })),
  ),
)

function props() {
  return {
    author: 'studio',
    posts,
    currentId: '2026-11-20',
    listKey: 'studio|',
    isStale: false,
    navigationDisabled: false,
    width: 360,
    emptyMessage: 'No matching posts.',
    postHref: (id: string) => `#${id}`,
    onPost: vi.fn(),
  }
}

test('jumps through the real virtual timeline without selecting a post and follows scrolling', async () => {
  const input = props()
  render(<PostList {...input} />)
  const select = screen.getByRole('combobox', { name: 'Jump to month' })
  const timeline = screen.getByLabelText('Post timeline')
  expect(select).toHaveValue('2026-11')
  fireEvent.change(select, { target: { value: '2021-03' } })
  await waitFor(() => expect(select).toHaveValue('2021-03'))
  expect(timeline.scrollTop).toBeGreaterThan(0)
  expect(screen.getByText('Post 2021-03-20')).toBeInTheDocument()
  expect(input.onPost).not.toHaveBeenCalled()
  fireEvent.scroll(timeline, { target: { scrollTop: 0 } })
  await waitFor(() => expect(select).toHaveValue('2026-11'))
  expect(timeline.querySelector('[aria-current="page"]')).toHaveAttribute(
    'data-post-id',
    input.currentId,
  )
})

test('replaces month targets after filtering and keeps an unavailable list disabled', async () => {
  const input = props()
  const { rerender } = render(<PostList {...input} />)
  const select = screen.getByRole('combobox', { name: 'Jump to month' })
  const filtered = posts.filter((post) => post.created_at.startsWith('2021-03'))
  rerender(<PostList {...input} posts={filtered} listKey="studio|tag=march" />)
  await waitFor(() => expect(select).toHaveValue('2021-03'))
  expect(screen.getAllByRole('option')).toHaveLength(1)
  rerender(<PostList {...input} posts={filtered} listKey="studio|tag=march" navigationDisabled />)
  expect(select).toBeDisabled()
  expect(input.onPost).not.toHaveBeenCalled()
})

test('keeps remaining rows visible when the anchored post leaves the same filtered list', () => {
  const input = props()
  const view = render(<PostList {...input} />)
  const timeline = screen.getByLabelText('Post timeline')
  act(() => timeline.scrollTo({ top: timeline.scrollHeight - timeline.clientHeight }))
  const remaining = posts.slice(0, 3)
  expect(remaining.some((post) => post.id === firstUnobscuredPost(timeline).id)).toBe(false)

  view.rerender(<PostList {...input} posts={remaining} />)

  const content = timeline.firstElementChild as HTMLElement
  const lastOffset = Math.max(0, Number.parseFloat(content.style.minHeight) - timeline.clientHeight)
  expect(timeline.scrollTop).toBeLessThanOrEqual(lastOffset)
  expect(remaining.some((post) => post.id === firstUnobscuredPost(timeline).id)).toBe(true)
  expect(input.onPost).not.toHaveBeenCalled()
})

test('omits the month selector for loading and empty results', () => {
  const input = props()
  const { rerender } = render(<PostList {...input} posts={undefined} navigationDisabled />)
  expect(screen.getByRole('status', { name: 'Loading posts' })).toBeVisible()
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  rerender(<PostList {...input} posts={[]} />)
  expect(screen.getByRole('status')).toHaveTextContent('No matching posts.')
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
})

type TimelineViewport = { width: number; height: number }
type TimelinePlace = { id: string | null; top: number }
type TimelineResize = {
  observer: ResizeObserver
  notify: ResizeObserverCallback
  targets: Set<Element>
  disconnect: () => void
}

function responsiveViewport(viewport: TimelineViewport) {
  const observed: TimelineResize[] = []
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(() => viewport.width)
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(() => viewport.height)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(() => viewport.height)
  vi.stubGlobal(
    'ResizeObserver',
    class implements ResizeObserver {
      readonly targets = new Set<Element>()
      readonly disconnect = vi.fn()
      constructor(notify: ResizeObserverCallback) {
        observed.push({
          observer: this,
          notify,
          targets: this.targets,
          disconnect: this.disconnect,
        })
      }
      observe(target: Element): void {
        this.targets.add(target)
      }
      unobserve(target: Element): void {
        this.targets.delete(target)
      }
    },
  )
  return {
    observed,
    resize: (target: Element): void => {
      const box = { inlineSize: viewport.width, blockSize: viewport.height }
      const entry: ResizeObserverEntry = {
        target,
        contentRect: new DOMRect(0, 0, viewport.width, viewport.height),
        borderBoxSize: [box],
        contentBoxSize: [box],
        devicePixelContentBoxSize: [box],
      }
      for (const observer of observed)
        if (observer.targets.has(target)) observer.notify([entry], observer.observer)
    },
  }
}

function firstUnobscuredPost(timeline: HTMLElement): TimelinePlace {
  for (const post of timeline.querySelectorAll('[data-post-id]')) {
    const row = post.closest('[data-post-row]')?.parentElement
    if (!row) continue
    const top = Number.parseFloat(row.style.transform.slice('translateY('.length))
    const height = Number.parseFloat(row.style.height)
    if (top + height > timeline.scrollTop + 32)
      return { id: post.getAttribute('data-post-id'), top: top - timeline.scrollTop }
  }
  throw new Error('No unobscured post in the virtual viewport')
}

test.each([false, true])(
  'keeps the exact bottom anchor across native clamps and rerenders, snippets=%s',
  (snippets) => {
    const viewport = { width: 330, height: 240 }
    const observer = responsiveViewport(viewport)
    const input = props()
    const rows = posts.map((post) => ({
      ...post,
      match: snippets ? { title: [], text: [{ text: 'A matching snippet', matched: true }] } : null,
    }))
    const view = render(<PostList {...input} posts={rows} width={viewport.width} />)
    const timeline = screen.getByLabelText('Post timeline')
    act(() => timeline.scrollTo({ top: timeline.scrollHeight - timeline.clientHeight }))
    const anchor = firstUnobscuredPost(timeline)
    const oldOffset = timeline.scrollTop
    viewport.width = 340
    viewport.height += 40
    act(() => timeline.scrollTo({ top: oldOffset }))
    // The physical extent follows viewport growth before any resize observer runs.
    expect(timeline.scrollTop).toBe(oldOffset)
    expect(firstUnobscuredPost(timeline)).toEqual(anchor)
    view.rerender(<PostList {...input} posts={rows} width={viewport.width} />)
    act(() => observer.resize(timeline))
    expect(firstUnobscuredPost(timeline)).toEqual(anchor)
    expect(timeline.scrollTop).toBeGreaterThan(oldOffset - 40)
    const restoredHeight = timeline.scrollHeight
    view.rerender(<PostList {...input} posts={rows} width={viewport.width} isStale />)
    expect(timeline.scrollHeight).toBe(restoredHeight)
    expect(firstUnobscuredPost(timeline)).toEqual(anchor)
    for (const width of [350, 360, 370, 380, 370, 360, 350, 340]) {
      viewport.width = width
      view.rerender(<PostList {...input} posts={rows} width={width} />)
      act(() => observer.resize(timeline))
      expect(firstUnobscuredPost(timeline)).toEqual(anchor)
    }
    view.unmount()
    expect(observer.observed.some((item) => vi.mocked(item.disconnect).mock.calls.length > 0)).toBe(
      true,
    )
  },
)

test('height-only reflow preserves the bottom row while a reader scroll establishes a fresh anchor', () => {
  const viewport = { width: 360, height: 240 }
  const observer = responsiveViewport(viewport)
  const input = props()
  const view = render(<PostList {...input} />)
  const timeline = screen.getByLabelText('Post timeline')
  const logicalHeight = timeline.scrollHeight
  act(() => timeline.scrollTo({ top: logicalHeight - viewport.height }))
  const anchor = firstUnobscuredPost(timeline)
  viewport.height += 50
  act(() => {
    timeline.scrollTo({ top: timeline.scrollTop })
    observer.resize(timeline)
  })
  expect(firstUnobscuredPost(timeline)).toEqual(anchor)
  expect(timeline.scrollHeight).toBe(logicalHeight + 50)
  act(() => timeline.scrollTo({ top: timeline.scrollTop - 500 }))
  const readerPlace = firstUnobscuredPost(timeline)
  expect(timeline.scrollHeight).toBe(logicalHeight)
  viewport.width = 420
  view.rerender(<PostList {...input} width={viewport.width} />)
  act(() => observer.resize(timeline))
  expect(firstUnobscuredPost(timeline)).toEqual(readerPlace)
})

test('month, selection and filter navigation replace a retained resize anchor', () => {
  const viewport = { width: 360, height: 240 }
  const observer = responsiveViewport(viewport)
  const input = props()
  const view = render(<PostList {...input} />)
  const timeline = screen.getByLabelText('Post timeline')
  act(() => timeline.scrollTo({ top: timeline.scrollHeight - viewport.height }))
  viewport.height = 300
  act(() => observer.resize(timeline))
  fireEvent.change(screen.getByRole('combobox', { name: 'Jump to month' }), {
    target: { value: '2023-11' },
  })
  const monthPlace = firstUnobscuredPost(timeline)
  expect(monthPlace.id).toBe('2023-11-20')
  viewport.width = 400
  view.rerender(<PostList {...input} width={viewport.width} />)
  expect(firstUnobscuredPost(timeline)).toEqual(monthPlace)
  view.rerender(<PostList {...input} width={viewport.width} currentId="2025-03-15" />)
  expect(timeline.querySelector('[aria-current="page"]')).toHaveAttribute(
    'data-post-id',
    '2025-03-15',
  )
  const selectedPlace = firstUnobscuredPost(timeline)
  viewport.width = 420
  view.rerender(<PostList {...input} width={viewport.width} currentId="2025-03-15" />)
  expect(firstUnobscuredPost(timeline)).toEqual(selectedPlace)
  view.rerender(
    <PostList
      {...input}
      posts={posts.slice(-4)}
      width={viewport.width}
      listKey="other-filter"
      currentId={undefined}
    />,
  )
  expect(timeline.scrollTop).toBe(0)
})
