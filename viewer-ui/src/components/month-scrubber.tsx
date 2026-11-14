import { ArrowUpToLine } from 'lucide-react'
import { useId } from 'react'

import { formatCount } from '@/lib/format'
import type { MonthTarget } from '@/lib/timeline'

type MonthScrubberProps = {
  months: readonly MonthTarget[]
  currentKey: string | undefined
  disabled: boolean
  onMonth: (month: MonthTarget) => void
}

type MonthYearGroup = { year: string; months: MonthTarget[] }

/** Jump through the available months without changing the open post or filters. */
export function MonthScrubber({ months, currentKey, disabled, onMonth }: MonthScrubberProps) {
  const id = useId()
  const current = months.find((month) => month.key === currentKey)
  const years = groupMonths(months)
  const jump = (key: string): void => {
    if (disabled) return
    const month = months.find((item) => item.key === key)
    if (month) onMonth(month)
  }
  const jumpToCurrent = current ? () => jump(current.key) : undefined

  return (
    <div className="flex shrink-0 items-center gap-2 border-b px-4 py-2">
      <label htmlFor={id} className="text-[12.5px] text-muted-foreground">
        Month
      </label>
      <select
        id={id}
        aria-label="Jump to month"
        value={current?.key ?? ''}
        disabled={disabled || months.length === 0}
        onChange={(event) => jump(event.target.value)}
        className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-[12.5px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
      >
        {!current && (
          <option value="" disabled>
            Choose month
          </option>
        )}
        {years.map(({ year, months: yearMonths }) => (
          <optgroup key={year} label={year}>
            {yearMonths.map((month) => (
              <option key={month.key} value={month.key}>
                {month.label} ({formatCount(month.count)})
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <button
        type="button"
        aria-label="Jump to month start"
        title="Jump to month start"
        disabled={disabled || !current}
        onClick={jumpToCurrent}
        className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-input bg-background text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-60"
      >
        <ArrowUpToLine aria-hidden="true" className="size-4" />
      </button>
    </div>
  )
}

function groupMonths(months: readonly MonthTarget[]): MonthYearGroup[] {
  const groups: MonthYearGroup[] = []
  for (const month of months) {
    const group = groups.at(-1)
    if (group?.year === month.year) group.months.push(month)
    else groups.push({ year: month.year, months: [month] })
  }
  return groups
}
