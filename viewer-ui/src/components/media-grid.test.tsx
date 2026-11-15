import { act, screen, waitFor } from '@testing-library/react'
import { createRef, useState, type Ref } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { MediaGrid, type MediaGridHandle } from '@/components/media-grid'
import type { MediaPage } from '@/lib/api.gen'
import { mediaAnchorAt, mediaGridLayout, mediaRowHeight, mediaRowIndex } from '@/lib/media-layout'
import { renderWithMediaActions as render } from '@/test/file-actions'
import { savedPost, savedVideo } from '@/test/post-fixtures'

let width = 1140
let immediateScrollEvents = true
const resizeObservers: TestResizeObserver[] = []
const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')

class TestResizeObserver implements ResizeObserver {
  callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
    resizeObservers.push(this)
  }
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  width = 1140
  immediateScrollEvents = true
  resizeObservers.length = 0
  vi.stubGlobal('ResizeObserver', TestResizeObserver)
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(400)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(() => width)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400)
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    const grid = this.querySelector<HTMLElement>('[data-media-grid]')
    return grid ? Number.parseFloat(grid.style.height) : 0
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value(this: HTMLElement, options: ScrollToOptions): void {
      this.scrollTop = Math.max(
        0,
        Math.min(options.top ?? this.scrollTop, this.scrollHeight - this.clientHeight),
      )
      if (immediateScrollEvents) this.dispatchEvent(new Event('scroll'))
    },
  })
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    const scrollTop = this.hasAttribute('data-media-grid')
      ? (this.parentElement?.scrollTop ?? 0)
      : 0
    return new DOMRect(0, -scrollTop, width, 400)
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, 'scrollTo', originalScrollTo)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
})

const photos = Array.from({ length: 2000 }, (_, index) => ({
  ...savedVideo,
  id: `photo-${index}`,
  kind: 'images' as const,
}))
const page: MediaPage = {
  items: photos,
  posts: { [savedPost.id]: savedPost },
  counts: { all: 2000, images: 2000, videos: 0, audio: 0, files: 0 },
  missing: 0,
}

function Harness({
  data = page,
  active = true,
  listKey = 'all',
  gridRef,
}: {
  data?: MediaPage
  active?: boolean
  listKey?: string
  gridRef?: Ref<MediaGridHandle>
}) {
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null)
  return (
    <div ref={setScroller} data-testid="scroller">
      <MediaGrid
        {...(gridRef ? { ref: gridRef } : {})}
        author="studio"
        page={data}
        scroller={scroller}
        active={active}
        listKey={listKey}
        onOpen={vi.fn()}
        renderFavorite={() => null}
      />
    </div>
  )
}

test('bounds a 2000-photo grid and restores focus to a distant virtualized tile', async () => {
  const ref = createRef<MediaGridHandle>()
  const { container } = render(<Harness gridRef={ref} />)
  await waitFor(() =>
    expect(container.querySelectorAll('[data-media-id]').length).toBeGreaterThan(0),
  )
  expect(container.querySelectorAll('[data-media-id]').length).toBeLessThan(200)
  expect(container.querySelector('[data-media-id="photo-1500"]')).toBeNull()
  let restored: Promise<boolean> | undefined
  act(() => {
    restored = ref.current?.focusItem('photo-1500')
  })
  await waitFor(() => expect(container.querySelector('[data-media-id="photo-1500"]')).toHaveFocus())
  await expect(restored).resolves.toBe(true)
  expect(screen.getByTestId('scroller').scrollTop).toBeGreaterThan(40_000)
  expect(container.querySelectorAll('[data-media-id]').length).toBeLessThan(200)
  await act(async () => {
    expect(await ref.current?.focusItem('missing')).toBe(false)
  })
})

test('scrolls an already mounted overscan tile into view before focusing it', async () => {
  const ref = createRef<MediaGridHandle>()
  const { container } = render(<Harness gridRef={ref} />)
  await waitFor(() => expect(container.querySelector('[data-media-id="photo-30"]')).not.toBeNull())
  let restored: Promise<boolean> | undefined
  act(() => {
    restored = ref.current?.focusItem('photo-30')
  })
  await waitFor(() => expect(container.querySelector('[data-media-id="photo-30"]')).toHaveFocus())
  await expect(restored).resolves.toBe(true)
  expect(screen.getByTestId('scroller').scrollTop).toBeGreaterThan(500)
})

test('keeps scroll across tab activity and resets it only for a new list selection', async () => {
  const ref = createRef<MediaGridHandle>()
  const { rerender, container } = render(<Harness gridRef={ref} />)
  const scroller = screen.getByTestId('scroller')
  await waitFor(() => expect(container.querySelector('[data-media-id]')).not.toBeNull())
  act(() => scroller.scrollTo({ top: 2000 }))
  rerender(<Harness active={false} gridRef={ref} />)
  expect(scroller.scrollTop).toBe(2000)
  expect(container.querySelector('[data-media-grid]')).toHaveAttribute('inert')
  await act(async () => {
    expect(await ref.current?.focusItem('photo-0')).toBe(false)
  })
  rerender(<Harness gridRef={ref} />)
  expect(scroller.scrollTop).toBe(2000)
  rerender(<Harness gridRef={ref} listKey="unseen" />)
  expect(scroller.scrollTop).toBe(0)
})

test('keeps the same top photo through repeated width changes and accepts a new user scroll', async () => {
  const { container } = render(<Harness />)
  const scroller = screen.getByTestId('scroller')
  await waitFor(() => expect(container.querySelector('[data-media-id]')).not.toBeNull())
  act(() => scroller.scrollTo({ top: 12_345 }))
  const original = mediaAnchorAt(mediaGridLayout(photos, 0, width), scroller.scrollTop)
  if (!original || original.kind !== 'tiles') throw new Error('Expected a middle photo')
  for (const nextWidth of [970, 720, 390, 280, 640, 1140]) {
    act(() => {
      width = nextWidth
      for (const observer of resizeObservers) observer.callback([], observer)
    })
    const layout = mediaGridLayout(photos, 0, width)
    const shown = mediaAnchorAt(layout, scroller.scrollTop)
    expect(shown?.kind === 'tiles' && mediaRowIndex(layout, shown.id)).toBe(
      mediaRowIndex(layout, original.id),
    )
  }
  act(() => scroller.scrollTo({ top: 3000 }))
  const chosen = mediaAnchorAt(mediaGridLayout(photos, 0, width), scroller.scrollTop)
  act(() => {
    width = 640
    for (const observer of resizeObservers) observer.callback([], observer)
  })
  const layout = mediaGridLayout(photos, 0, width)
  const shown = mediaAnchorAt(layout, scroller.scrollTop)
  expect(chosen?.kind === 'tiles' && mediaRowIndex(layout, chosen.id)).toBe(
    shown?.kind === 'tiles' && mediaRowIndex(layout, shown.id),
  )
})

test.each(['viewport', 'element'] as const)(
  'mounts the anchored rows before delayed scroll events during a %s resize',
  async (resized) => {
    const { container, rerender } = render(<Harness />)
    const scroller = screen.getByTestId('scroller')
    await waitFor(() => expect(container.querySelector('[data-media-id]')).not.toBeNull())
    act(() => scroller.scrollTo({ top: 12_345 }))
    const original = mediaAnchorAt(mediaGridLayout(photos, 0, width), scroller.scrollTop)
    if (!original || original.kind !== 'tiles') throw new Error('Expected a middle photo')
    immediateScrollEvents = false
    for (const nextWidth of [970, 720, 390, 280, 640, 1140]) {
      act(() => {
        width = nextWidth
        if (resized === 'viewport') window.dispatchEvent(new Event('resize'))
        else for (const observer of resizeObservers) observer.callback([], observer)
        // A frame may arrive before the native scroll event for the restored offset.
        expect(container.querySelector(`[data-media-id="${original.id}"]`)).not.toBeNull()
        const layout = mediaGridLayout(photos, 0, width)
        const shown = mediaAnchorAt(layout, scroller.scrollTop)
        expect(shown?.kind === 'tiles' && mediaRowIndex(layout, shown.id)).toBe(
          mediaRowIndex(layout, original.id),
        )
      })
    }
    rerender(<Harness listKey="unseen" />)
    expect(scroller.scrollTop).toBe(0)
    expect(container.querySelector('[data-media-id="photo-0"]')).not.toBeNull()
  },
)

test('remeasures different section rows when a view change keeps the same row count', async () => {
  const items = photos.slice(0, 12).map((item, index) => ({ ...item, removed: index >= 6 }))
  const first = { ...page, items }
  const { container, rerender } = render(<Harness data={first} />)
  const grid = container.querySelector<HTMLElement>('[data-media-grid]')
  await waitFor(() =>
    expect(screen.getByRole('heading', { name: 'Removed by the author · 6' })).toBeVisible(),
  )
  const initialHeight = Number.parseFloat(grid?.style.height ?? '0')
  rerender(<Harness data={{ ...page, items: photos.slice(0, 12), missing: 2 }} listKey="images" />)
  expect(screen.queryByRole('heading')).not.toBeInTheDocument()
  await waitFor(() =>
    expect(screen.getByText('2 more pieces of this view are not downloaded.')).toBeVisible(),
  )
  expect(Number.parseFloat(grid?.style.height ?? '0')).toBeCloseTo(initialHeight - 36)
})

test('resolves superseded and unmounted focus requests without leaving a pending promise', async () => {
  const ref = createRef<MediaGridHandle>()
  const { container, unmount } = render(<Harness gridRef={ref} />)
  await waitFor(() => expect(container.querySelector('[data-media-id]')).not.toBeNull())
  let replaced: Promise<boolean> | undefined
  let chosen: Promise<boolean> | undefined
  act(() => {
    replaced = ref.current?.focusItem('photo-1000')
    chosen = ref.current?.focusItem('photo-1600')
  })
  await expect(replaced).resolves.toBe(false)
  await waitFor(() => expect(container.querySelector('[data-media-id="photo-1600"]')).toHaveFocus())
  await expect(chosen).resolves.toBe(true)
  let cancelled: Promise<boolean> | undefined
  act(() => {
    cancelled = ref.current?.focusItem('photo-500')
    unmount()
  })
  await expect(cancelled).resolves.toBe(false)
})

test('retains its original tile through browser scroll clamping near the end of a resize', async () => {
  width = 390
  const { container } = render(<Harness />)
  const scroller = screen.getByTestId('scroller')
  await waitFor(() => expect(container.querySelector('[data-media-id]')).not.toBeNull())
  act(() => scroller.scrollTo({ top: scroller.scrollHeight }))
  const original = mediaAnchorAt(mediaGridLayout(photos, 0, width), scroller.scrollTop)
  if (!original || original.kind !== 'tiles') throw new Error('Expected a trailing photo')
  act(() => {
    width = 280
    const shorter = mediaGridLayout(photos, 0, width)
    // A browser can clamp the live offset before delivering its next scroll event.
    scroller.scrollTop =
      shorter.rows.reduce((height, row) => height + mediaRowHeight(row, shorter), 0) - 400
    for (const observer of resizeObservers) observer.callback([], observer)
  })
  act(() => {
    width = 640
    for (const observer of resizeObservers) observer.callback([], observer)
  })
  const restored = mediaGridLayout(photos, 0, width)
  const shown = mediaAnchorAt(restored, scroller.scrollTop)
  expect(shown?.kind === 'tiles' && mediaRowIndex(restored, shown.id)).toBe(
    mediaRowIndex(restored, original.id),
  )
})
