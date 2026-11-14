import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Sidebar, type SidebarProps } from '@/components/sidebar'
import type { Author } from '@/lib/api.gen'
import { NO_FILTERS, type Filters } from '@/lib/filters'

vi.mock('@/hooks/use-element-width', () => ({ useElementWidth: () => 360 }))
vi.mock('@/components/post-list', () => ({ PostList: ({ emptyMessage }: { emptyMessage: string }) => <p>{emptyMessage}</p> }))

afterEach(() => vi.useRealTimers())

const author: Author = {
  name: 'author', title: 'Studio', description: '', avatar_url: null, cover_url: null,
  posts: 8, locked: 2, unseen: 3, favorites: 1,
  storage: { videos: 0, images: 0, files: 0, audio: 0 },
}

function props(filters: Filters = {}): SidebarProps {
  return {
    author, filters, posts: { rows: [], months: [], total: 0 }, tags: [{ tag: '2024', count: 3 }],
    loading: false, updating: false, error: null, onRetry: vi.fn(), onFilters: vi.fn(),
    onPost: vi.fn(), postHref: id => `#${id}`,
  }
}

describe('Sidebar filters', () => {
  it('preserves all other fields when one filter changes', () => {
    const filters: Filters = { q: 'paint', tag: '2024', kind: 'images', unseen: 1, fav: 1, locked: 1, incomplete: 1, order: 'oldest' }
    const input = props(filters)
    render(<Sidebar {...input} />)
    fireEvent.click(screen.getByRole('button', { name: 'Videos' }))
    expect(input.onFilters).toHaveBeenCalledWith({ ...filters, kind: 'videos' }, { replace: false })
    fireEvent.click(screen.getByRole('button', { name: 'Locked' }))
    expect(input.onFilters).toHaveBeenLastCalledWith({ ...filters, locked: undefined }, { replace: false })
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort order' }), { target: { value: 'newest' } })
    expect(input.onFilters).toHaveBeenLastCalledWith({ ...filters, order: undefined }, { replace: false })
  })

  it('clears every field and preserves numeric tag strings', () => {
    const input = props({ q: 'test', tag: '2024', locked: 1, incomplete: 1 })
    render(<Sidebar {...input} />)
    expect(screen.getByRole('combobox', { name: 'Tag' })).toHaveValue('2024')
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(input.onFilters).toHaveBeenCalledExactlyOnceWith(NO_FILTERS)
  })

  it('clears an unsent search when the URL has only a kind filter', () => {
    vi.useFakeTimers()
    const input = props({ kind: 'images' })
    const { rerender } = render(<Sidebar {...input} />)
    const search = screen.getByRole('textbox', { name: 'Search posts' })
    fireEvent.change(search, { target: { value: 'pending-search' } })
    act(() => vi.advanceTimersByTime(47))
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    rerender(<Sidebar {...input} filters={{}} />)
    expect(search).toHaveValue('')
    act(() => vi.advanceTimersByTime(450))
    expect(input.onFilters).toHaveBeenCalledExactlyOnceWith(NO_FILTERS)
  })

  it('retains an exact selected tag while the tag request fails and retries independently', () => {
    const input = props({ tag: 'Unavailable tag' })
    const retryTags = vi.fn()
    render(<Sidebar {...input} tags={[]} tagsError={new Error('Tags are unavailable.')} onRetryTags={retryTags} error={new Error('Posts are unavailable.')} posts={undefined} />)
    expect(screen.getByRole('combobox', { name: 'Tag' })).toHaveValue('Unavailable tag')
    expect(screen.getByText('Tags are unavailable.')).toHaveAttribute('role', 'alert')
    expect(screen.getByText('Posts are unavailable.')).toHaveAttribute('role', 'alert')
    fireEvent.click(screen.getByRole('button', { name: 'Retry tags' }))
    fireEvent.click(screen.getByRole('button', { name: 'Retry posts' }))
    expect(retryTags).toHaveBeenCalledTimes(1)
    expect(input.onRetry).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('No posts match the filters.')).not.toBeInTheDocument()
  })

  it('distinguishes an empty author from an empty filtered list', () => {
    const input = props()
    const { rerender } = render(<Sidebar {...input} />)
    expect(screen.getByText('No posts match the filters.')).toBeVisible()
    rerender(<Sidebar {...input} author={{ ...author, title: '', posts: 0 }} />)
    expect(screen.getByRole('complementary', { name: 'Posts of author' })).toBeVisible()
    expect(screen.getByText('No posts yet.')).toBeVisible()
  })
})
