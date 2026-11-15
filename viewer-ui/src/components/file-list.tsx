import { FileRow } from '@/components/file-row'
import { MediaSection } from '@/components/removed-media'
import { useMediaList, type MediaListProps } from '@/hooks/use-media-list'

const FILE_ROW_HEIGHT = 64

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
        const post = page.posts[row.item.post_id]
        if (!post) throw new Error(`Missing post metadata for media ${row.item.id}`)
        return (
          <FileRow
            key={key}
            author={author}
            item={row.item}
            post={post}
            active={active}
            style={{ ...style, height: FILE_ROW_HEIGHT }}
          />
        )
      })}
    </div>
  )
}
