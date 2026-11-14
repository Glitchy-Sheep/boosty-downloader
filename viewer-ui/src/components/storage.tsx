import { cn } from 'cn'

import { formatSize } from '@/lib/format'
import { STORAGE_LOOKS, type StoragePart } from '@/lib/storage'

type StorageProps = { parts: StoragePart[]; className?: string }

/** The legend names every kind; the bar preserves its colors in high contrast. */
export function StorageBar({ parts, className }: StorageProps) {
  return (
    <div aria-hidden="true" data-storage-bar="" className={cn('flex h-(--bar) gap-[3px] forced-color-adjust-none', className)}>
      {parts.map(({ kind, share }) => (
        <span
          key={kind}
          data-kind={kind}
          className={cn('min-w-[calc(var(--bar)/2)] rounded-full', STORAGE_LOOKS[kind].fill)}
          style={{ flex: `${share} 1 0` }}
        />
      ))}
    </div>
  )
}

export function StorageLegend({ parts, className }: StorageProps) {
  return (
    <ul className={cn('grid grid-cols-2 gap-x-4 gap-y-1', className)}>
      {parts.map(({ kind, bytes }) => (
        <li key={kind} data-kind={kind} className="flex min-w-0 items-center gap-1.5 whitespace-nowrap">
          <span
            aria-hidden="true"
            className={cn('size-2 shrink-0 rounded-full forced-color-adjust-none', STORAGE_LOOKS[kind].fill)}
          />
          <span className="text-muted-foreground">{STORAGE_LOOKS[kind].label}</span>
          <span>{formatSize(bytes)}</span>
        </li>
      ))}
    </ul>
  )
}
