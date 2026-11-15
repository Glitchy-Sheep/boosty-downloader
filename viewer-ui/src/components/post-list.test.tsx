import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render as renderUi, screen, waitFor } from '@testing-library/react'
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
    return content instanceof HTMLElement ? Number.parseFloat(content.style.height) || 0 : 0
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

test('omits the month selector for loading and empty results', () => {
  const input = props()
  const { rerender } = render(<PostList {...input} posts={undefined} navigationDisabled />)
  expect(screen.getByRole('status', { name: 'Loading posts' })).toBeVisible()
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  rerender(<PostList {...input} posts={[]} />)
  expect(screen.getByRole('status')).toHaveTextContent('No matching posts.')
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
})
