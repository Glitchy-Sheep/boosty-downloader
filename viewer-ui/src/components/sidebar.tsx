import { cn } from 'cn'
import { AudioLines, Film, Heart, ImageIcon, LoaderCircle, Lock, Paperclip, X, type LucideIcon } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'

import { AuthorAvatar } from '@/components/author-avatar'
import { PostList } from '@/components/post-list'
import { SearchBox } from '@/components/search-box'
import { useElementWidth } from '@/hooks/use-element-width'
import type { Author, PostList as PostPage, TagCount } from '@/lib/api.gen'
import { filtersSearchParams, hasFilters, KINDS, NO_FILTERS, type Filters, type Kind } from '@/lib/filters'
import { formatCount, plural } from '@/lib/format'

export type SidebarProps = {
  author: Author
  filters: Filters
  posts: PostPage | undefined
  tags: TagCount[]
  currentId?: string
  searchResetRevision?: number
  loading: boolean
  updating: boolean
  error: Error | null
  tagsError?: Error | null
  onRetry: () => void
  onRetryTags?: () => void
  onFilters: (next: Filters, options?: { replace?: boolean }) => void
  onPost: (id: string) => void
  postHref: (id: string) => string
}

type SetFilters = (patch: Filters, replace?: boolean) => void
type FilterControls = { filters: Filters; setFilters: SetFilters }
type KindLook = { label: string; icon: LucideIcon }
type StateKey = keyof Pick<Filters, 'unseen' | 'fav' | 'locked' | 'incomplete'>
type StateLook = { key: StateKey; label: string; marker?: ReactNode }

const KIND_LOOKS: Record<Kind, KindLook> = {
  videos: { label: 'Videos', icon: Film },
  images: { label: 'Photos', icon: ImageIcon },
  files: { label: 'Files', icon: Paperclip },
  audio: { label: 'Audio', icon: AudioLines },
}
const STATES: readonly StateLook[] = [
  { key: 'unseen', label: 'Unseen', marker: <span aria-hidden="true" className="size-1.5 rounded-full bg-primary" /> },
  { key: 'fav', label: 'Favorites', marker: <Heart aria-hidden="true" className="size-3" /> },
  { key: 'locked', label: 'Locked', marker: <Lock aria-hidden="true" className="size-3" /> },
  { key: 'incomplete', label: 'Incomplete' },
]
const CHIP = 'h-7 rounded-full border border-border px-3 text-[12.5px] font-medium text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:border-primary/40 aria-pressed:bg-primary-soft aria-pressed:text-primary @max-[340px]/sidebar:px-2.5'
const SELECT = 'h-8 min-w-0 rounded-md border border-input bg-background px-2 text-[12.5px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50'
const RETRY = 'rounded-sm text-primary underline outline-none focus-visible:ring-3 focus-visible:ring-ring/50'

/** Filters and the timeline stay mounted while another post opens. */
export function Sidebar(props: SidebarProps) {
  const { author, filters, posts, tags, currentId, loading, updating, error, tagsError, onRetry, onRetryTags, onFilters, onPost, postHref } = props
  const root = useRef<HTMLElement>(null)
  const [searchClearRevision, setSearchClearRevision] = useState(0)
  const width = useElementWidth(root)
  const setFilters: SetFilters = (patch, replace = false) => onFilters({ ...filters, ...patch }, { replace })
  const clearFilters = (): void => {
    setSearchClearRevision(revision => revision + 1)
    onFilters({ ...NO_FILTERS })
  }
  const emptyMessage = author.posts === 0 ? 'No posts yet.' : 'No posts match the filters.'

  return (
    <aside
      ref={root}
      aria-label={`Posts of ${author.title || author.name}`}
      className="@container/sidebar flex h-full min-h-0 min-w-0 flex-1 flex-col bg-card"
    >
      <div className="flex shrink-0 flex-col gap-3 border-b px-4 pt-4 pb-3">
        <AuthorSummary author={author} />
        <SearchBox
          value={filters.q ?? ''}
          onSearch={q => setFilters({ q: q || undefined }, true)}
          resetRevision={searchClearRevision}
          navigationRevision={props.searchResetRevision}
        />
        <KindFilters filters={filters} setFilters={setFilters} />
        <StateFilters filters={filters} setFilters={setFilters} />
        <div className="flex min-w-0 gap-2">
          <TagFilter tags={tags} selected={filters.tag} onChange={tag => setFilters({ tag })} />
          <OrderFilter filters={filters} setFilters={setFilters} />
        </div>
        {tagsError && (
          <div className="text-[12px]">
            <p role="alert">{tagsError.message || 'Could not load tags.'}</p>
            {onRetryTags && <button type="button" onClick={onRetryTags} className={RETRY}>Retry tags</button>}
          </div>
        )}
        <div className="flex h-5 items-center gap-2 text-[12.5px] text-muted-foreground">
          <span className="font-medium text-foreground tabular-nums">{resultCount(posts, loading, error)}</span>
          {(loading || updating) && <LoaderCircle aria-label="Updating posts" className="size-3.5 animate-spin" />}
          {hasFilters(filters) && (
            <button
              type="button"
              aria-label="Clear filters"
              onClick={clearFilters}
              className="ml-auto inline-flex items-center gap-0.5 rounded-md px-1 outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <X aria-hidden="true" className="size-3" />Clear
            </button>
          )}
        </div>
      </div>
      {error && (
        <div className="border-b px-4 py-3 text-[13px]">
          <p role="alert">{error.message || 'Could not load posts.'}</p>
          <button type="button" onClick={onRetry} className={cn(RETRY, 'mt-1')}>Retry posts</button>
        </div>
      )}
      {width !== null && (!error || posts) && (
        <PostList
          author={author.name}
          posts={posts?.rows}
          currentId={currentId}
          listKey={`${author.name}|${filtersSearchParams(filters)}`}
          isStale={updating}
          width={width}
          emptyMessage={emptyMessage}
          postHref={postHref}
          onPost={onPost}
        />
      )}
    </aside>
  )
}

function resultCount(posts: PostPage | undefined, loading: boolean, error: Error | null): string {
  if (posts) return plural(posts.total, 'post')
  if (error) return 'Posts unavailable'
  if (loading) return 'Loading posts...'
  return '0 posts'
}

function AuthorSummary({ author }: { author: Author }) {
  return (
    <div className="flex items-center gap-3">
      <AuthorAvatar author={author} className="size-10" />
      <div className="min-w-0">
        <div className="truncate text-[15px] leading-tight font-semibold">{author.title || author.name}</div>
        <div className="mt-1 text-[12.5px] text-muted-foreground">
          {plural(author.posts, 'post')}, <span className="font-medium text-primary">{formatCount(author.unseen)} unseen</span>
          {author.favorites > 0 && <span className="text-rose-500">, {formatCount(author.favorites)} favorites</span>}
        </div>
      </div>
    </div>
  )
}

function KindFilters({ filters, setFilters }: FilterControls) {
  return (
    <div role="group" aria-label="Media kind" className="flex flex-wrap items-center gap-1">
      <FilterChip pressed={!filters.kind} onClick={() => setFilters({ kind: undefined })}>All</FilterChip>
      {KINDS.map(kind => (
        <KindChip
          key={kind}
          kind={kind}
          pressed={filters.kind === kind}
          onClick={() => setFilters({ kind: filters.kind === kind ? undefined : kind })}
        />
      ))}
    </div>
  )
}

function StateFilters({ filters, setFilters }: FilterControls) {
  return (
    <div role="group" aria-label="Post state" className="flex flex-wrap items-center gap-1">
      {STATES.map(({ key, label, marker }) => (
        <FilterChip key={key} pressed={Boolean(filters[key])} onClick={() => setFilters({ [key]: filters[key] ? undefined : 1 })}>
          {marker}{label}
        </FilterChip>
      ))}
    </div>
  )
}

function OrderFilter({ filters, setFilters }: FilterControls) {
  return (
    <select
      aria-label="Sort order"
      value={filters.order ?? 'newest'}
      onChange={event => setFilters({ order: event.target.value === 'oldest' ? 'oldest' : undefined })}
      className={cn(SELECT, 'shrink-0')}
    >
      <option value="newest">Newest first</option><option value="oldest">Oldest first</option>
    </select>
  )
}

type ChipProps = { pressed: boolean; onClick: () => void; children: ReactNode; label?: string }
function FilterChip({ pressed, onClick, children, label }: ChipProps) {
  return (
    <button type="button" aria-label={label} aria-pressed={pressed} onClick={onClick} className={cn(CHIP, 'inline-flex items-center justify-center gap-1.5')}>
      {children}
    </button>
  )
}

function KindChip({ kind, pressed, onClick }: { kind: Kind; pressed: boolean; onClick: () => void }) {
  const { icon: Icon, label } = KIND_LOOKS[kind]
  return (
    <FilterChip label={label} pressed={pressed} onClick={onClick}>
      <Icon aria-hidden="true" className="hidden size-3.5 @max-[340px]/sidebar:block" />
      <span className="@max-[340px]/sidebar:sr-only">{label}</span>
    </FilterChip>
  )
}

function TagFilter({ tags, selected, onChange }: { tags: TagCount[]; selected: string | undefined; onChange: (tag: string | undefined) => void }) {
  const missingSelection = selected !== undefined && !tags.some(item => item.tag === selected)
  return (
    <select aria-label="Tag" value={selected ?? ''} onChange={event => onChange(event.target.value || undefined)} className={cn(SELECT, 'flex-1')}>
      <option value="">All tags</option>
      {missingSelection && <option value={selected}>{selected}</option>}
      {tags.map(({ tag, count }) => <option key={tag} value={tag}>{tag} ({formatCount(count)})</option>)}
    </select>
  )
}
