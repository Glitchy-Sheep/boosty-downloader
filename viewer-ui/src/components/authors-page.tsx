import { Lock } from 'lucide-react'
import { useId } from 'react'

import { AuthorArtwork } from '@/components/author-artwork'
import { AuthorAvatar } from '@/components/author-avatar'
import { StorageBar, StorageLegend } from '@/components/storage'
import type { Author } from '@/lib/api.gen'
import { formatCount, formatSize, plural } from '@/lib/format'
import { libraryStorage, STORAGE_LOOKS, storageNoun, storageParts, type StoragePart } from '@/lib/storage'

function title(author: Author): string {
  return author.title || author.name
}

function compareAuthors(first: Author, second: Author): number {
  return title(first).localeCompare(title(second)) || first.name.localeCompare(second.name)
}

export function AuthorsPage({ authors }: { authors: Author[] }) {
  const ordered = [...authors].sort(compareAuthors)
  const posts = authors.reduce((total, author) => total + author.posts, 0)
  const unseen = authors.reduce((total, author) => total + author.unseen, 0)

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1180px] px-4 pt-8 pb-12 sm:px-8 sm:pt-12 sm:pb-16">
        <div className="flex flex-col gap-x-12 gap-y-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.015em]">Authors</h1>
            <p className="mt-1.5 text-muted-foreground">
              {plural(authors.length, 'author')} · {plural(posts, 'post')} · {formatCount(unseen)} unseen
            </p>
          </div>
          {authors.length > 1 && <LibraryStorage authors={authors} />}
        </div>
        <div className="mt-6 grid grid-cols-[repeat(auto-fill,minmax(min(320px,100%),1fr))] gap-4 sm:mt-8 sm:gap-5">
          {ordered.map((author) => (
            <AuthorCard key={author.name} author={author} alone={authors.length === 1} />
          ))}
        </div>
        {authors.length === 0 && (
          <p role="status" className="mt-8 text-muted-foreground">
            No authors yet. Download posts to this library to see them here.
          </p>
        )}
      </div>
    </div>
  )
}

function LibraryStorage({ authors }: { authors: Author[] }) {
  const { total, parts } = storageParts(libraryStorage(authors))
  if (total === 0) return null

  return (
    <section aria-label="Disk space" data-storage="" className="w-full max-w-[560px] lg:w-[520px]">
      <p className="flex items-baseline gap-2">
        <span className="text-[22px] leading-none font-semibold tracking-tight">{formatSize(total)}</span>
        <span className="text-[13px] text-muted-foreground">of {storageNoun(parts)} on disk</span>
      </p>
      <StorageBar parts={parts} className="mt-3 [--bar:10px]" />
      {parts.length > 1 && (
        <StorageLegend parts={parts} className="mt-2.5 text-[12.5px] sm:flex sm:flex-wrap sm:gap-x-3.5" />
      )}
    </section>
  )
}

function storageDescription(total: number, parts: StoragePart[]): string {
  if (total === 0) return 'No media on disk'
  const summary = `${formatSize(total)} of ${storageNoun(parts)} on disk`
  if (parts.length === 1) return summary
  const kinds = parts
    .map(({ kind, bytes }) => `${STORAGE_LOOKS[kind].label.toLowerCase()} ${formatSize(bytes)}`)
    .join(', ')
  return `${summary}: ${kinds}`
}

function cardDescription(author: Author, total: number, parts: StoragePart[]): string {
  const sentences = [storageDescription(total, parts)]
  if (author.unseen > 0) sentences.push(`${formatCount(author.unseen)} unseen`)
  return `${sentences.join('. ')}.`
}

function AuthorCard({ author, alone }: { author: Author; alone: boolean }) {
  const id = useId()
  const { total, parts } = storageParts(author.storage)

  return (
    <a
      href={`/a/${encodeURIComponent(author.name)}`}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-about`}
      className="group relative row-span-3 grid grid-cols-1 grid-rows-subgrid gap-y-0 overflow-hidden rounded-lg border bg-card outline-none transition duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-[0_18px_40px_-20px_rgb(0_0_0/0.55)] focus-visible:ring-3 focus-visible:ring-ring/50 motion-reduce:transition-none motion-reduce:hover:translate-y-0"
    >
      <div>
        <div aria-hidden="true" className="relative aspect-[3/1] overflow-hidden bg-muted">
          <AuthorArtwork
            src={author.cover_url}
            className="size-full object-cover transition duration-500 group-hover:scale-[1.04] motion-reduce:transition-none motion-reduce:group-hover:scale-100"
          />
          <div className="absolute inset-0 bg-linear-to-t from-card/60 to-transparent" />
        </div>
        <div className="px-5">
          <AuthorAvatar author={author} className="-mt-9 size-[72px] ring-4 ring-card" />
          <h2 id={`${id}-title`} className="mt-3 text-[17px] font-semibold tracking-tight wrap-anywhere">
            {title(author)}
          </h2>
          <p className="mt-1 line-clamp-2 text-[13.5px] leading-relaxed text-muted-foreground wrap-anywhere">
            {author.description}
          </p>
        </div>
      </div>
      <span id={`${id}-about`} hidden>{cardDescription(author, total, parts)}</span>
      <AuthorStorage author={author} alone={alone} total={total} parts={parts} />
      <AuthorCounts author={author} />
    </a>
  )
}

type AuthorStorageProps = {
  author: Author
  alone: boolean
  total: number
  parts: StoragePart[]
}

function AuthorStorage({ author, alone, total, parts }: AuthorStorageProps) {
  return (
    <div data-storage={author.name} className="px-5 pt-4 pb-5">
      {total === 0 && <p className="text-[13px] text-muted-foreground">No media on disk</p>}
      {total > 0 && <StorageTotal alone={alone} total={total} parts={parts} />}
    </div>
  )
}

function StorageTotal({ alone, total, parts }: Omit<AuthorStorageProps, 'author'>) {
  const suffix = parts.length === 1 ? ' on disk' : ' of media on disk'
  return (
    <>
      <p className="text-[13px] text-muted-foreground">
        <span className="text-[15px] font-semibold text-foreground">{formatSize(total)}</span>
        {parts.length === 1 && ` of ${storageNoun(parts)}`}
        <span className={alone ? undefined : 'sr-only'}>{suffix}</span>
      </p>
      <StorageBar parts={parts} className="mt-2 [--bar:8px]" />
      {parts.length > 1 && <StorageLegend parts={parts} className="mt-2.5 text-[12px]" />}
    </>
  )
}

function AuthorCounts({ author }: { author: Author }) {
  return (
    <div className="mx-5 mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 border-t pt-4 text-[12.5px] text-muted-foreground">
      <span className="font-medium text-foreground">{plural(author.posts, 'post')}</span>
      <span className="inline-flex items-center gap-1">
        <Lock aria-hidden="true" className="size-3" />
        {formatCount(author.locked)} locked
      </span>
      {author.unseen > 0 && (
        <span className="ml-auto rounded-full bg-primary-soft px-2.5 py-0.5 font-medium text-primary">
          {formatCount(author.unseen)} unseen
        </span>
      )}
    </div>
  )
}
