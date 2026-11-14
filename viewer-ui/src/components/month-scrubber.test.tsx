import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MonthScrubber } from '@/components/month-scrubber'
import type { MonthTarget } from '@/lib/timeline'

const MONTHS: readonly MonthTarget[] = [
  { key: '2026-11', label: 'November 2026', year: '2026', count: 1200, firstPostIndex: 1 },
  { key: '2026-01', label: 'January 2026', year: '2026', count: 2, firstPostIndex: 1202 },
  { key: '2021-03', label: 'March 2021', year: '2021', count: 3, firstPostIndex: 1205 },
  { key: '2019-01', label: 'January 2019', year: '2019', count: 1, firstPostIndex: 1209 },
]

describe('MonthScrubber', () => {
  it.each(['newest', 'oldest'])('groups available months by year in %s list order', (order) => {
    const months = order === 'newest' ? MONTHS : MONTHS.toReversed()
    render(
      <MonthScrubber months={months} currentKey="2021-03" disabled={false} onMonth={vi.fn()} />,
    )
    const select = screen.getByRole('combobox', { name: 'Jump to month' })
    expect(select).toHaveValue('2021-03')
    expect(
      within(select)
        .getAllByRole('group')
        .map((group) => group.getAttribute('label')),
    ).toEqual(order === 'newest' ? ['2026', '2021', '2019'] : ['2019', '2021', '2026'])
    expect(
      within(select)
        .getAllByRole('option')
        .map((option) => option.getAttribute('value')),
    ).toEqual(months.map(({ key }) => key))
    expect(
      within(select).getByRole('option', { name: 'November 2026 (1,200)' }),
    ).toBeInTheDocument()
    expect(within(select).queryByRole('option', { name: /2020/ })).not.toBeInTheDocument()
  })

  it('sends the chosen target while keeping the current month controlled by scroll position', () => {
    const onMonth = vi.fn()
    const { rerender } = render(
      <MonthScrubber months={MONTHS} currentKey="2026-11" disabled={false} onMonth={onMonth} />,
    )
    const select = screen.getByRole('combobox', { name: 'Jump to month' })
    fireEvent.change(select, { target: { value: '2021-03' } })
    expect(onMonth).toHaveBeenCalledExactlyOnceWith(MONTHS[2])
    expect(select).toHaveValue('2026-11')
    rerender(
      <MonthScrubber months={MONTHS} currentKey="2021-03" disabled={false} onMonth={onMonth} />,
    )
    expect(select).toHaveValue('2021-03')
    expect(onMonth).toHaveBeenCalledTimes(1)
  })

  it('rejects stale choices while the list is unavailable', () => {
    const onMonth = vi.fn()
    render(<MonthScrubber months={MONTHS} currentKey="2026-11" disabled onMonth={onMonth} />)
    const select = screen.getByRole('combobox', { name: 'Jump to month' })
    expect(select).toBeDisabled()
    fireEvent.change(select, { target: { value: '2021-03' } })
    const start = screen.getByRole('button', { name: 'Jump to month start' })
    expect(start).toBeDisabled()
    fireEvent.click(start)
    expect(onMonth).not.toHaveBeenCalled()
  })

  it('jumps to the current month start repeatedly without selecting another month', () => {
    const onMonth = vi.fn()
    const { rerender } = render(
      <MonthScrubber months={MONTHS} currentKey="2021-03" disabled={false} onMonth={onMonth} />,
    )
    const start = screen.getByRole('button', { name: 'Jump to month start' })
    expect(start).toBeEnabled()
    expect(start).toHaveAttribute('title', 'Jump to month start')
    fireEvent.click(start)
    fireEvent.click(start)
    expect(onMonth).toHaveBeenCalledTimes(2)
    expect(onMonth).toHaveBeenNthCalledWith(1, MONTHS[2])
    expect(onMonth).toHaveBeenNthCalledWith(2, MONTHS[2])
    expect(screen.getByRole('combobox', { name: 'Jump to month' })).toHaveValue('2021-03')
    rerender(
      <MonthScrubber months={MONTHS} currentKey="2019-01" disabled={false} onMonth={onMonth} />,
    )
    fireEvent.click(start)
    expect(onMonth).toHaveBeenNthCalledWith(3, MONTHS[3])
  })

  it('offers only new filtered choices and ignores a removed selection', () => {
    const onMonth = vi.fn()
    const { rerender } = render(
      <MonthScrubber months={MONTHS} currentKey="2026-11" disabled={false} onMonth={onMonth} />,
    )
    const filtered = MONTHS.filter(({ key }) => key === '2021-03')
    rerender(
      <MonthScrubber months={filtered} currentKey="2021-03" disabled={false} onMonth={onMonth} />,
    )
    const select = screen.getByRole('combobox', { name: 'Jump to month' })
    expect(within(select).getAllByRole('option')).toHaveLength(1)
    expect(select).toHaveValue('2021-03')
    fireEvent.change(select, { target: { value: '2026-11' } })
    expect(onMonth).not.toHaveBeenCalled()
  })

  it.each([undefined, '2000-01'])(
    'does not invent a visible month when current is %s',
    (currentKey) => {
      const onMonth = vi.fn()
      render(
        <MonthScrubber
          months={MONTHS}
          currentKey={currentKey}
          disabled={false}
          onMonth={onMonth}
        />,
      )
      const select = screen.getByRole('combobox', { name: 'Jump to month' })
      expect(select).toHaveValue('')
      expect(within(select).getByRole('option', { name: 'Choose month' })).toBeDisabled()
      const start = screen.getByRole('button', { name: 'Jump to month start' })
      expect(start).toBeDisabled()
      fireEvent.click(start)
      expect(onMonth).not.toHaveBeenCalled()
    },
  )

  it('disables an empty collection without sending navigation', () => {
    const onMonth = vi.fn()
    render(<MonthScrubber months={[]} currentKey={undefined} disabled={false} onMonth={onMonth} />)
    expect(screen.getByRole('combobox', { name: 'Jump to month' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Jump to month start' })).toBeDisabled()
    expect(onMonth).not.toHaveBeenCalled()
  })
})
