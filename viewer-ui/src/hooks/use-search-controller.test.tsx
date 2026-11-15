import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SearchBox } from '@/components/search-box'
import { useSearchController } from '@/hooks/use-search-controller'

type HarnessProps = {
  visible: boolean
  active?: boolean
  value?: string
  navigationRevision?: number
  onSearch: (text: string) => void
}

function Harness({
  visible,
  active = true,
  value = '',
  navigationRevision = 0,
  onSearch,
}: HarnessProps) {
  const controller = useSearchController({ value, active, navigationRevision, onSearch })
  return (
    <>
      <button type="button" onClick={controller.reset}>
        Reset filters
      </button>
      {visible && <SearchBox value={value} onSearch={onSearch} controller={controller} />}
    </>
  )
}

afterEach(() => vi.useRealTimers())

describe('persistent search controller', () => {
  it('keeps typing and its debounce when the sidebar closes and remounts', () => {
    vi.useFakeTimers()
    const onSearch = vi.fn()
    const view = render(<Harness visible onSearch={onSearch} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'unfinished text' } })
    act(() => {
      vi.advanceTimersByTime(100)
    })
    view.rerender(<Harness visible={false} onSearch={onSearch} />)
    act(() => {
      vi.advanceTimersByTime(99)
    })
    expect(onSearch).not.toHaveBeenCalled()
    view.rerender(<Harness visible onSearch={onSearch} />)
    expect(screen.getByRole('textbox')).toHaveValue('unfinished text')
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(onSearch).toHaveBeenCalledExactlyOnceWith('unfinished text')
  })

  it('publishes while the sidebar is closed but pauses when Posts is inactive', () => {
    vi.useFakeTimers()
    const onSearch = vi.fn()
    const view = render(<Harness visible onSearch={onSearch} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'first' } })
    view.rerender(<Harness visible={false} onSearch={onSearch} />)
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(onSearch).toHaveBeenCalledExactlyOnceWith('first')
    view.rerender(<Harness visible value="first" onSearch={onSearch} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'second' } })
    view.rerender(<Harness visible={false} active={false} value="first" onSearch={onSearch} />)
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(onSearch).toHaveBeenCalledTimes(1)
    view.rerender(<Harness visible={false} value="first" onSearch={onSearch} />)
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(onSearch.mock.calls).toEqual([['first'], ['second']])
  })

  it('keeps newer typing across remount while the URL acknowledges an earlier search', () => {
    vi.useFakeTimers()
    const onSearch = vi.fn()
    const view = render(<Harness visible onSearch={onSearch} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'first' } })
    act(() => {
      vi.advanceTimersByTime(200)
    })
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'first second' } })
    view.rerender(<Harness visible={false} onSearch={onSearch} />)
    view.rerender(<Harness visible value="first" onSearch={onSearch} />)
    expect(screen.getByRole('textbox')).toHaveValue('first second')
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(onSearch.mock.calls).toEqual([['first'], ['first second']])
  })

  it('does not resurrect the old URL after clearing filters or publish a duplicate clear', () => {
    vi.useFakeTimers()
    const onSearch = vi.fn()
    const view = render(<Harness visible value="old" onSearch={onSearch} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '' } })
    act(() => {
      vi.advanceTimersByTime(100)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }))
    view.rerender(<Harness visible={false} value="old" onSearch={onSearch} />)
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    view.rerender(<Harness visible value="old" onSearch={onSearch} />)
    expect(screen.getByRole('textbox')).toHaveValue('')
    expect(onSearch).not.toHaveBeenCalled()
    view.rerender(<Harness visible value="" onSearch={onSearch} />)
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('resets a closed draft when history changes only other filters', () => {
    vi.useFakeTimers()
    const onSearch = vi.fn()
    const view = render(<Harness visible onSearch={onSearch} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'pending' } })
    view.rerender(<Harness visible={false} navigationRevision={1} onSearch={onSearch} />)
    act(() => {
      vi.advanceTimersByTime(500)
    })
    view.rerender(<Harness visible navigationRevision={1} onSearch={onSearch} />)
    expect(screen.getByRole('textbox')).toHaveValue('')
    expect(onSearch).not.toHaveBeenCalled()
  })
})
