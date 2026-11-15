import { cn } from 'cn'

import type { MediaItem } from '@/lib/api.gen'
import { FILE_PRESENTATION } from '@/lib/file-presentation'

type FileTypeIconProps = { type: MediaItem['file_type']; className?: string }

export function FileTypeIcon({ type, className }: FileTypeIconProps) {
  const presentation = FILE_PRESENTATION[type]
  const Icon = presentation.icon
  return (
    <span
      role="img"
      aria-label={presentation.label}
      className={cn(
        'grid size-9 shrink-0 place-items-center rounded-lg',
        presentation.tone,
        className,
      )}
    >
      {presentation.letters ? (
        <span aria-hidden="true" className="text-[10.5px] leading-none font-bold tracking-tight">
          {presentation.letters}
        </span>
      ) : (
        <Icon aria-hidden="true" className="size-[18px]" />
      )}
    </span>
  )
}
