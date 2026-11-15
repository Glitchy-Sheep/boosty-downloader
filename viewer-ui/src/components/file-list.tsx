import { Link } from '@tanstack/react-router'
import { cn } from 'cn'
import { Download, FileText } from 'lucide-react'

import { MediaSection, REMOVED_MEDIA_ART, REMOVED_MEDIA_LABEL } from '@/components/removed-media'
import { useMediaList, type MediaListProps } from '@/hooks/use-media-list'
import { formatDate } from '@/lib/dates'
import { NO_FILTERS } from '@/lib/filters'
import { formatSize } from '@/lib/format'
import { mediaPath } from '@/lib/media-paths'

const FILE_ROW_HEIGHT = 64

/** Download belongs to the file; the row itself has no action. */
export function FileList(props: MediaListProps) {
  const { author, page, active } = props
  const list = useMediaList(props, FILE_ROW_HEIGHT)
  return (
    <div
      data-file-list=""
      inert={!active}
      className="relative w-full"
      style={{ height: list.height }}
    >
      {list.rows.map(({ key, start, row }) => {
        const style = { transform: `translateY(${start}px)` }
        if (row.kind !== 'item')
          return <MediaSection key={key} row={row} style={style} ruled={false} />
        const item = row.item
        const post = page.posts[item.post_id]
        if (!post) throw new Error(`Missing post metadata for media ${item.id}`)
        const name = item.filename || item.path.split('/').at(-1) || 'File'
        return (
          <div
            key={key}
            data-media-id={item.id}
            data-removed={item.removed ? '' : undefined}
            className="group/removed absolute top-0 left-0 flex w-full items-center gap-2 border-b px-2 hover:bg-foreground/3 focus-within:bg-foreground/3 sm:gap-3"
            style={{ ...style, height: FILE_ROW_HEIGHT }}
          >
            <FileText
              data-art=""
              aria-hidden="true"
              className={cn(
                'size-7 shrink-0 text-muted-foreground',
                item.removed && REMOVED_MEDIA_ART,
              )}
            />
            <div className="min-w-0 flex-1">
              <div
                title={name}
                className={cn(
                  'relative truncate text-[14px] font-medium',
                  item.removed && 'text-muted-foreground',
                )}
              >
                {name}
                <span className="sr-only">{item.removed ? REMOVED_MEDIA_LABEL : ''}</span>
              </div>
              <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[12px] text-muted-foreground">
                <span className="shrink-0 tabular-nums">{formatSize(item.size)}</span>
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
            <a
              href={mediaPath(author, item.path)}
              download={name}
              aria-label={`Download ${name}${item.removed ? REMOVED_MEDIA_LABEL : ''}`}
              title={`Download ${name}`}
              className="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Download aria-hidden="true" className="size-4" />
            </a>
          </div>
        )
      })}
    </div>
  )
}
