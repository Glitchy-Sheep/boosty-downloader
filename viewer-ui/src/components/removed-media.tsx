import { cn } from 'cn'
import type { CSSProperties } from 'react'

import { formatCount, plural } from '@/lib/format'
import { mediaSectionHeight, type MediaSectionRow } from '@/lib/media-layout'

export const REMOVED_MEDIA_LABEL = ', removed by the author'
export const REMOVED_MEDIA_ART =
  'opacity-70 transition-opacity duration-200 group-hover/removed:opacity-100 group-focus-within/removed:opacity-100 group-has-[[aria-expanded=true]]/removed:opacity-100 group-data-[state=open]/removed:opacity-100'

type MediaSectionProps = { row: MediaSectionRow; style?: CSSProperties; ruled?: boolean }

export function MediaSection({ row, style, ruled = true }: MediaSectionProps) {
  const place = { ...style, height: mediaSectionHeight(row) }
  if (row.kind === 'missing') {
    return (
      <p
        data-missing-note=""
        className="absolute top-0 left-0 flex w-full items-center justify-center text-center text-[12.5px] text-muted-foreground"
        style={place}
      >
        {plural(row.count, row.first ? 'piece' : 'more piece')} of this view{' '}
        {row.count === 1 ? 'is' : 'are'} not downloaded.
      </p>
    )
  }
  return (
    <div
      data-removed-heading=""
      className="absolute top-0 left-0 flex w-full flex-col justify-end pb-3"
      style={place}
    >
      <div className={cn('pt-3', ruled && !row.first && 'border-t')}>
        <h2 className="text-[13.5px] font-medium">
          Removed by the author{' '}
          <span className="font-normal text-muted-foreground">· {formatCount(row.count)}</span>
        </h2>
        <p className="mt-0.5 text-[12.5px] text-muted-foreground">Your copies stay on disk.</p>
      </div>
    </div>
  )
}
