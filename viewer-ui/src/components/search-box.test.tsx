import { act, fireEvent, render, screen } from '@testing-library/react'
import { createRef } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SearchBox } from '@/components/search-box'
import { TabActive } from '@/lib/author-tab'

afterEach(() => vi.useRealTimers())

describe('SearchBox', () => {
  it('holds an unsent draft while hidden and publishes it once the tab returns', () => {
    vi.useFakeTimers()
    const search = vi.fn()
    const box = (active: boolean) => (
      <TabActive value={active}>
        <SearchBox value="" onSearch={search} />
      </TabActive>
    )
    const { rerender } = render(box(true))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'retained draft' } })
    act(() => {
      vi.advanceTimersByTime(100)
    })
    rerender(box(false))
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(search).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox')).toHaveValue('retained draft')
    rerender(box(true))
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(search).toHaveBeenCalledExactlyOnceWith('retained draft')
  })

  it('shares its input with keyboard navigation and keeps clear-button focus', () => {
    const input = createRef<HTMLInputElement>()
    const { unmount } = render(<SearchBox value="needle" onSearch={vi.fn()} inputRef={input} />)
    const field = screen.getByRole('textbox', { name: 'Search posts' })
    expect(input.current).toBe(field)
    input.current?.focus()
    input.current?.select()
    expect(field).toHaveFocus()
    expect(input.current?.selectionStart).toBe(0)
    expect(input.current?.selectionEnd).toBe(6)
    fireEvent.click(screen.getByRole('button', { name: 'Clear the search' }))
    expect(field).toHaveValue('')
    expect(field).toHaveFocus()
    unmount()
    expect(input.current).toBeNull()
  })

  it('sends only the final text after typing pauses', () => {
    vi.useFakeTimers()
    const search = vi.fn()
    render(<SearchBox value="" onSearch={search} />)
    const input = screen.getByRole('textbox', { name: 'Search posts' })
    fireEvent.change(input, { target: { value: 'ш' } })
    act(() => {
      vi.advanceTimersByTime(150)
    })
    fireEvent.change(input, { target: { value: 'шейдер' } })
    act(() => {
      vi.advanceTimersByTime(199)
    })
    expect(search).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(search).toHaveBeenCalledExactlyOnceWith('шейдер')
  })

  it('adopts Back navigation and cancels a pending draft', () => {
    vi.useFakeTimers()
    const search = vi.fn()
    const { rerender } = render(<SearchBox value="current" onSearch={search} />)
    const input = screen.getByRole('textbox', { name: 'Search posts' })
    fireEvent.change(input, { target: { value: 'unfinished' } })
    rerender(<SearchBox value="previous" onSearch={search} />)
    expect(input).toHaveValue('previous')
    act(() => {
      vi.advanceTimersByTime(250)
    })
    expect(search).not.toHaveBeenCalled()
  })

  it('keeps newer typing when the URL acknowledges an earlier search', () => {
    vi.useFakeTimers()
    const search = vi.fn()
    const { rerender } = render(<SearchBox value="" onSearch={search} />)
    const input = screen.getByRole('textbox', { name: 'Search posts' })
    fireEvent.change(input, { target: { value: '2024' } })
    act(() => {
      vi.advanceTimersByTime(200)
    })
    fireEvent.change(input, { target: { value: '2024 art' } })
    rerender(<SearchBox value="2024" onSearch={search} />)
    expect(input).toHaveValue('2024 art')
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(search.mock.calls).toEqual([['2024'], ['2024 art']])
  })

  it('clears and focuses the field, then lets Escape leave an empty field', () => {
    vi.useFakeTimers()
    const search = vi.fn()
    render(<SearchBox value="text" onSearch={search} />)
    const input = screen.getByRole('textbox', { name: 'Search posts' })
    fireEvent.click(screen.getByRole('button', { name: 'Clear the search' }))
    expect(input).toHaveValue('')
    expect(input).toHaveFocus()
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(search).toHaveBeenCalledExactlyOnceWith('')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(input).not.toHaveFocus()
  })

  it('does not publish a draft after the component unmounts', () => {
    vi.useFakeTimers()
    const search = vi.fn()
    const { unmount } = render(<SearchBox value="" onSearch={search} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'draft' } })
    unmount()
    act(() => {
      vi.advanceTimersByTime(250)
    })
    expect(search).not.toHaveBeenCalled()
  })

  it('cancels a pending draft when Back changes only other filters', () => {
    vi.useFakeTimers()
    const search = vi.fn()
    const { rerender } = render(<SearchBox value="" onSearch={search} navigationRevision={0} />)
    const input = screen.getByRole('textbox', { name: 'Search posts' })
    input.focus()
    fireEvent.change(input, { target: { value: 'pending' } })
    act(() => {
      vi.advanceTimersByTime(47)
    })
    rerender(<SearchBox value="" onSearch={search} navigationRevision={1} />)
    expect(input).toHaveValue('')
    expect(input).toHaveFocus()
    act(() => {
      vi.advanceTimersByTime(450)
    })
    expect(search).not.toHaveBeenCalled()
  })

  it('clears immediately while the old URL search is still present', () => {
    vi.useFakeTimers()
    const search = vi.fn()
    const { rerender } = render(<SearchBox value="previous" onSearch={search} resetRevision={0} />)
    const input = screen.getByRole('textbox', { name: 'Search posts' })
    input.focus()
    fireEvent.change(input, { target: { value: 'pending' } })
    rerender(<SearchBox value="previous" onSearch={search} resetRevision={1} />)
    expect(input).toHaveValue('')
    expect(input).toHaveFocus()
    act(() => {
      vi.advanceTimersByTime(450)
    })
    expect(search).not.toHaveBeenCalled()
    rerender(<SearchBox value="" onSearch={search} resetRevision={1} />)
    expect(input).toHaveValue('')
  })
})
