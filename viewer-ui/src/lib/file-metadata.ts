import type { MediaItem } from '@/lib/api.gen'
import { fileKind, fileNameOnDisk } from '@/lib/file-presentation'
import { formatSize } from '@/lib/format'

export function fileMetadata(item: MediaItem): string {
  return `${fileKind(fileNameOnDisk(item), item.file_type)} · ${formatSize(item.size)}`
}
