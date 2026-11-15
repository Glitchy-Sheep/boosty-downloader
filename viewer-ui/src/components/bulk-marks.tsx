import { CheckCheck, ChevronDown, LoaderCircle } from 'lucide-react'
import { Dialog, DropdownMenu } from 'radix-ui'
import { useRef, useState } from 'react'

import { useBulkMarks, type BulkMarkSelection } from '@/hooks/use-bulk-marks'
import type { BulkMarksProgressResponse, PostFilters, PostList } from '@/lib/api.gen'
import { useTabActive } from '@/lib/author-tab'
import { toPostFilters, type Filters, type Kind } from '@/lib/filters'
import { formatCount, plural } from '@/lib/format'
import { countMarkChanges } from '@/lib/post-marks'

type BulkMarksProps = {
  author: string
  filters: Filters
  posts: PostList | undefined
  disabled: boolean
}
type Confirmation = {
  kind: 'confirmation'
  selection: BulkMarkSelection
  remainingCount: number | null
  repair: boolean
}
type BulkDialog = Confirmation | { kind: 'operation' } | null
type BulkController = ReturnType<typeof useBulkMarks>

const BUTTON =
  'inline-flex min-h-7 items-center justify-center gap-1.5 rounded-md border px-2 text-[12px] font-medium whitespace-nowrap outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50'
const MENU_ITEM =
  'cursor-default rounded-sm px-2.5 py-2 text-[13px] outline-none data-highlighted:bg-muted data-highlighted:text-primary data-disabled:opacity-50'
const KIND_LABELS: Record<Kind, string> = {
  images: 'Photos',
  videos: 'Videos',
  files: 'Files',
  audio: 'Audio',
}

/** Bulk actions keep the confirmed filters while the reader continues browsing. */
export function BulkMarks({ author, filters, posts, disabled }: BulkMarksProps) {
  const active = useTabActive()
  const bulk = useBulkMarks(author)
  const [dialog, setDialog] = useState<BulkDialog>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  if (!active && dialog !== null) setDialog(null)
  if (!active && menuOpen) setMenuOpen(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const seenCount = countMarkChanges(posts?.rows ?? [], true)
  const unseenCount = countMarkChanges(posts?.rows ?? [], false)
  const unavailable = disabled || posts === undefined || bulk.blocked

  const choose = (seen: boolean): void => {
    if (unavailable) return
    const changeCount = countMarkChanges(posts?.rows ?? [], seen)
    if (!changeCount) return
    const selection = { author, filters: toPostFilters(filters), seen, changeCount }
    setDialog({ kind: 'confirmation', selection, remainingCount: changeCount, repair: false })
  }
  const retry = (): void => {
    const selection = bulk.operation?.selection
    if (!selection) return
    const sameFilters = JSON.stringify(selection.filters) === JSON.stringify(toPostFilters(filters))
    const remainingCount =
      !disabled && posts && sameFilters ? countMarkChanges(posts.rows, selection.seen) : null
    setDialog({ kind: 'confirmation', selection, remainingCount, repair: true })
  }
  const confirm = (): void => {
    if (dialog?.kind !== 'confirmation') return
    if (bulk.start(dialog.selection)) setDialog({ kind: 'operation' })
  }

  return (
    <>
      {bulk.pending ? (
        <button
          ref={trigger}
          type="button"
          onClick={() => setDialog({ kind: 'operation' })}
          className={BUTTON}
          aria-label="Show marking progress"
        >
          <LoaderCircle aria-hidden="true" className="size-3 motion-safe:animate-spin" />
          {progressLabel(bulk)}
        </button>
      ) : (
        <DropdownMenu.Root open={active && menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenu.Trigger asChild>
            <button
              ref={trigger}
              type="button"
              className={BUTTON}
              aria-label="Mark posts"
              disabled={(unavailable || seenCount + unseenCount === 0) && !bulk.operation}
            >
              <CheckCheck aria-hidden="true" className="size-3.5" />
              {bulk.operation?.status === 'error' ? 'Marking failed' : 'Mark posts'}
              <ChevronDown aria-hidden="true" className="size-3" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={6}
              onCloseAutoFocus={(event) => {
                if (dialog || !active) event.preventDefault()
              }}
              className="z-40 min-w-48 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg"
            >
              <DropdownMenu.Item
                disabled={unavailable || seenCount === 0}
                className={MENU_ITEM}
                onSelect={() => choose(true)}
              >
                Mark all as seen
              </DropdownMenu.Item>
              <DropdownMenu.Item
                disabled={unavailable || unseenCount === 0}
                className={MENU_ITEM}
                onSelect={() => choose(false)}
              >
                Mark all as unseen
              </DropdownMenu.Item>
              {bulk.operation && (
                <DropdownMenu.Item
                  className={MENU_ITEM}
                  onSelect={() => setDialog({ kind: 'operation' })}
                >
                  Last marking result
                </DropdownMenu.Item>
              )}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      )}
      {bulk.operation?.status === 'error' && !dialog && (
        <span role="alert" className="sr-only">
          {bulk.operation.error} Completed changes were kept.
        </span>
      )}
      <Dialog.Root
        open={active && dialog !== null}
        onOpenChange={(open) => {
          if (!open) setDialog(null)
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
          <Dialog.Content
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              if (active && trigger.current?.isConnected) trigger.current.focus()
            }}
            className="fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border bg-card p-6 text-card-foreground shadow-xl outline-none"
          >
            {dialog?.kind === 'confirmation' ? (
              <ConfirmationView
                confirmation={dialog}
                blocked={bulk.blocked}
                onCancel={() => setDialog(null)}
                onConfirm={confirm}
              />
            ) : (
              <OperationView bulk={bulk} onClose={() => setDialog(null)} onRetry={retry} />
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  )
}

function confirmationTitle(confirmation: Confirmation): string {
  const action = confirmation.selection.seen ? 'seen' : 'unseen'
  if (confirmation.remainingCount === null) return `Retry marking posts as ${action}?`
  return `Mark ${plural(confirmation.remainingCount, 'post')} as ${action}?`
}

function ConfirmationView({
  confirmation,
  blocked,
  onCancel,
  onConfirm,
}: {
  confirmation: Confirmation
  blocked: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { selection, repair, remainingCount } = confirmation
  return (
    <>
      <Dialog.Title className="text-lg leading-snug font-semibold">
        {confirmationTitle(confirmation)}
      </Dialog.Title>
      <Dialog.Description className="mt-2 text-sm leading-relaxed text-muted-foreground">
        {repair
          ? 'Retry the original filters. Completed changes are kept.'
          : 'This applies to the selected filters. Locked posts keep their marks.'}
      </Dialog.Description>
      {remainingCount === null && (
        <p className="mt-3 text-sm text-muted-foreground">
          The remaining count is unavailable. You originally confirmed{' '}
          {plural(selection.changeCount, 'post')}.
        </p>
      )}
      <FilterSummary filters={selection.filters} />
      <div className="mt-6 flex flex-wrap justify-end gap-2">
        <button type="button" className={BUTTON} onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          disabled={blocked}
          onClick={onConfirm}
          className={`${BUTTON} border-transparent bg-primary text-primary-foreground hover:bg-primary/90`}
        >
          Mark as {selection.seen ? 'seen' : 'unseen'}
        </button>
      </div>
    </>
  )
}

function operationTitle(bulk: BulkController): string {
  switch (bulk.operation?.status) {
    case 'success':
      return 'Posts marked'
    case 'error':
      return 'Marking failed'
    default:
      return 'Marking posts'
  }
}

function OperationView({
  bulk,
  onClose,
  onRetry,
}: {
  bulk: BulkController
  onClose: () => void
  onRetry: () => void
}) {
  const operation = bulk.operation
  return (
    <>
      <Dialog.Title className="text-lg leading-snug font-semibold">
        {operationTitle(bulk)}
      </Dialog.Title>
      <Dialog.Description className="mt-2 text-sm leading-relaxed text-muted-foreground">
        {operation?.status === 'error'
          ? 'Completed changes were kept. You can retry the same filters.'
          : 'Closing this window does not cancel changes already being saved.'}
      </Dialog.Description>
      {bulk.pending && <ProgressView bulk={bulk} />}
      {operation?.status === 'success' && (
        <p role="status" className="mt-4 text-sm">
          Marked {plural(operation.count ?? 0, 'post')} as{' '}
          {operation.selection.seen ? 'seen' : 'unseen'}.
        </p>
      )}
      {operation?.status === 'error' && (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {operation.error}
        </p>
      )}
      {operation && <FilterSummary filters={operation.selection.filters} />}
      <div className="mt-6 flex flex-wrap justify-end gap-2">
        <button type="button" className={BUTTON} onClick={onClose}>
          Close
        </button>
        {operation?.status === 'error' && (
          <button type="button" className={BUTTON} disabled={bulk.blocked} onClick={onRetry}>
            Retry marking
          </button>
        )}
      </div>
    </>
  )
}

function progressLabel(bulk: BulkController): string {
  const progress = bulk.progress
  if (!progress?.active || progress.total === null) return 'Marking...'
  return `${formatCount(progress.completed)} / ${formatCount(progress.total)}`
}

function ProgressView({ bulk }: { bulk: BulkController }) {
  const progress = bulk.progress
  return (
    <div className="mt-4 text-sm" role="status">
      {progress?.active ? (
        <>
          <p className="tabular-nums">{progressText(progress)}</p>
          <progress
            aria-label="Marking progress"
            value={progress.total ? progress.completed : undefined}
            max={progress.total || undefined}
            className="mt-3 h-2 w-full accent-primary"
          />
          <p className="mt-2 text-muted-foreground">{plural(progress.changed, 'post')} changed</p>
        </>
      ) : (
        <p>Waiting for the marking result...</p>
      )}
      {bulk.progressError && (
        <p className="mt-2 text-muted-foreground">Progress is unavailable. Marking continues.</p>
      )}
    </div>
  )
}

function progressText(progress: BulkMarksProgressResponse): string {
  if (progress.total === null) return `${plural(progress.completed, 'post')} processed`
  return `${formatCount(progress.completed)} of ${formatCount(progress.total)} posts processed`
}

function FilterSummary({ filters }: { filters: PostFilters }) {
  const labels: string[] = []
  if (filters.q) labels.push(`Search: ${filters.q}`)
  if (filters.kind) labels.push(KIND_LABELS[filters.kind])
  if (filters.unseen) labels.push('Unseen')
  if (filters.fav) labels.push('Favorites')
  if (filters.tag) labels.push(`#${filters.tag}`)
  if (filters.locked) labels.push('Locked')
  if (filters.incomplete) labels.push('Incomplete')
  if (!labels.length) labels.push('All posts')
  return (
    <ul aria-label="Selected filters" className="mt-4 flex flex-wrap gap-1.5">
      {labels.map((label) => (
        <li
          key={label}
          className="max-w-full rounded-md bg-secondary px-2 py-1 text-xs break-words text-secondary-foreground"
        >
          {label}
        </li>
      ))}
    </ul>
  )
}
