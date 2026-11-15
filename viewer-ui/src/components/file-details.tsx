import { FileName } from '@/components/file-name'
import type { MediaItem } from '@/lib/api.gen'
import { fileExecutionLabel, fileNameOnDisk } from '@/lib/file-presentation'

/** The displayed name is the file the operating system acts on. */
export function FileTitle({ item, wrap = false }: { item: MediaItem; wrap?: boolean }) {
  const execution = fileExecutionLabel(item.file_type)
  return (
    <div className="flex min-w-0 items-start gap-2 text-[14px] font-medium">
      <FileName name={fileNameOnDisk(item)} wrap={wrap} />
      {execution && (
        <span
          data-page-generated="true"
          className="mt-0.5 shrink-0 rounded border px-1 text-[10px] leading-4 font-normal text-muted-foreground select-none"
        >
          {execution}
        </span>
      )}
    </div>
  )
}
