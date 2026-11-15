import { cn } from 'cn'
import { ArrowDownWideNarrow, ArrowUpNarrowWide, Heart, LoaderCircle } from 'lucide-react'

import type { MediaViewCounts } from '@/lib/api.gen'
import { formatCount } from '@/lib/format'
import { MEDIA_VIEWS, type MediaSearch, type MediaView } from '@/lib/media-filters'

type MediaToolbarProps = {
  filters: MediaSearch
  counts: MediaViewCounts | undefined
  updating: boolean
  onChange: (patch: MediaSearch) => void
}

const VIEW_LABELS: Record<MediaView, string> = {
  all: 'All',
  images: 'Photos',
  videos: 'Videos',
  audio: 'Audio',
  files: 'Files',
}
const CHIP =
  'inline-flex h-8 shrink-0 items-center justify-center gap-1 rounded-full border border-border px-3.5 text-[13px] font-medium whitespace-nowrap text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50'
const SELECTED = 'border-primary/40 bg-primary-soft text-primary'

/** Counts and filters describe the same canonical media selection. */
export function MediaToolbar({ filters, counts, updating, onChange }: MediaToolbarProps) {
  const oldest = filters.order === 'oldest'
  const OrderIcon = oldest ? ArrowUpNarrowWide : ArrowDownWideNarrow
  return (
    <div className="shrink-0 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-[1400px] flex-wrap items-center gap-2 px-2 py-3 md:px-6">
        <div
          role="group"
          aria-label="Media views"
          className="-mx-1 flex max-w-full gap-1 overflow-x-auto px-1"
        >
          {MEDIA_VIEWS.map((view) => (
            <button
              key={view}
              type="button"
              aria-pressed={(filters.view ?? 'all') === view}
              onClick={() => onChange({ view: view === 'all' ? undefined : view })}
              className={cn(CHIP, (filters.view ?? 'all') === view && SELECTED)}
            >
              {VIEW_LABELS[view]}{' '}
              <span className="tabular-nums opacity-70">
                {counts ? formatCount(counts[view]) : '…'}
              </span>
            </button>
          ))}
        </div>
        {updating && (
          <span role="status" aria-label="Updating media">
            <LoaderCircle
              aria-hidden="true"
              className="size-4 text-muted-foreground motion-safe:animate-spin"
            />
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            aria-pressed={filters.unseen === 1}
            onClick={() => onChange({ unseen: filters.unseen === 1 ? undefined : 1 })}
            title="Hide media of seen posts and media played to the end"
            className={cn(CHIP, filters.unseen === 1 && SELECTED)}
          >
            <span aria-hidden="true" className="size-1.5 rounded-full bg-primary" />
            Unseen
          </button>
          <button
            type="button"
            aria-pressed={filters.fav === 1}
            aria-label="Favorites only"
            title="Favorites only"
            onClick={() => onChange({ fav: filters.fav === 1 ? undefined : 1 })}
            className={cn(
              CHIP,
              'px-2.5',
              filters.fav === 1 && 'border-rose-500/40 bg-rose-500/10 text-rose-500',
            )}
          >
            <Heart
              aria-hidden="true"
              className="size-4"
              fill={filters.fav === 1 ? 'currentColor' : 'none'}
            />
          </button>
          <button
            type="button"
            aria-pressed={oldest}
            aria-label="Oldest first"
            onClick={() => onChange({ order: oldest ? undefined : 'oldest' })}
            className={cn(CHIP, oldest && SELECTED)}
          >
            <OrderIcon aria-hidden="true" className="size-4" />
            <span className="hidden sm:inline">{oldest ? 'Oldest first' : 'Newest first'}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
