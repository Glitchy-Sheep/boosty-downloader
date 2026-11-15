import { Link } from '@tanstack/react-router'
import { cn } from 'cn'
import type { CSSProperties } from 'react'

import { FileActions } from '@/components/file-actions'
import { FileContextMenu } from '@/components/file-context-menu'
import { FileTitle } from '@/components/file-details'
import { FileTypeIcon } from '@/components/file-type-icon'
import { REMOVED_MEDIA_ART, REMOVED_MEDIA_LABEL } from '@/components/removed-media'
import { useMediaFileActions } from '@/hooks/use-file-actions'
import type { MediaItem, MediaPost } from '@/lib/api.gen'
import { formatDate } from '@/lib/dates'
import { fileMetadata } from '@/lib/file-metadata'
import { displayFileName, fileNameOnDisk } from '@/lib/file-presentation'
import { NO_FILTERS } from '@/lib/filters'

type FileRowProps = {
  author: string
  item: MediaItem
  post: MediaPost
  active: boolean
  style: CSSProperties
}

/** Only the named controls act on a file; its row remains selectable text. */
export function FileRow({ author, item, post, active, style }: FileRowProps) {
  const { actions, local } = useMediaFileActions(author, item)
  const label = displayFileName(fileNameOnDisk(item))
  return (
    <FileContextMenu actions={actions} enabled={local} active={active} label={label}>
      <div
        data-media-id={item.id}
        data-file-action-container=""
        data-removed={item.removed ? '' : undefined}
        className="group/removed absolute top-0 left-0 flex w-full items-center gap-2 border-b px-2 hover:bg-foreground/3 focus-within:bg-foreground/3 sm:gap-3"
        style={style}
      >
        <span data-art="" className={cn('shrink-0', item.removed && REMOVED_MEDIA_ART)}>
          <FileTypeIcon type={item.file_type} />
        </span>
        <div className={cn('relative min-w-0 flex-1', item.removed && 'text-muted-foreground')}>
          <FileTitle item={item} />
          {item.removed && <span className="sr-only">{REMOVED_MEDIA_LABEL}</span>}
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[12px] text-muted-foreground">
            <span className="min-w-0 truncate tabular-nums" title={fileMetadata(item)}>
              {fileMetadata(item)}
            </span>
            <span aria-hidden="true">·</span>
            <Link
              to="/a/$author/p/$postId"
              params={{ author, postId: item.post_id }}
              search={NO_FILTERS}
              className="min-w-0 truncate hover:text-foreground"
              title={post.title}
            >
              {post.title}
            </Link>
            <span className="hidden shrink-0 sm:inline">· {formatDate(item.created_at)}</span>
          </div>
        </div>
        <FileActions actions={actions} mode="file" label={label} active={active} />
      </div>
    </FileContextMenu>
  )
}
