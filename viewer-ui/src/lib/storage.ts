import type { Author, MediaStorage } from '@/lib/api.gen'

export type StorageKind = keyof MediaStorage

/** One downloaded kind's recorded bytes and share of the total. */
export type StoragePart = {
  kind: StorageKind
  bytes: number
  share: number
}

export type StorageBreakdown = {
  total: number
  parts: StoragePart[]
}

type StorageLook = {
  label: string
  fill: string
}

const STORAGE_KINDS = ['videos', 'images', 'files', 'audio'] as const satisfies readonly StorageKind[]

/** Storage colors follow the media kinds; the file color stays visible on white cards. */
export const STORAGE_LOOKS: Readonly<Record<StorageKind, StorageLook>> = {
  videos: { label: 'Videos', fill: 'bg-pink-500 dark:bg-pink-400' },
  images: { label: 'Photos', fill: 'bg-violet-500 dark:bg-violet-400' },
  audio: { label: 'Audio', fill: 'bg-cyan-500 dark:bg-cyan-400' },
  files: { label: 'Files', fill: 'bg-yellow-400 ring-1 ring-black/15 ring-inset dark:ring-0' },
}

/** Return nonzero kinds, biggest first; equal sizes keep the media-kind order. */
export function storageParts(storage: MediaStorage): StorageBreakdown {
  const total = STORAGE_KINDS.reduce((sum, kind) => sum + storage[kind], 0)
  const parts = STORAGE_KINDS.filter((kind) => storage[kind] > 0)
    .map((kind) => ({ kind, bytes: storage[kind], share: storage[kind] / total }))
    .sort((first, second) => second.bytes - first.bytes)
  return { total, parts }
}

/** Name the sole kind when present, or the combined media otherwise. */
export function storageNoun(parts: readonly StoragePart[]): string {
  if (parts.length === 1) return STORAGE_LOOKS[parts[0].kind].label.toLowerCase()
  return 'media'
}

/** Sum the indexed media totals without inspecting local files. */
export function libraryStorage(authors: readonly Author[]): MediaStorage {
  const sum = (kind: StorageKind): number =>
    authors.reduce((total, author) => total + author.storage[kind], 0)
  return { videos: sum('videos'), images: sum('images'), files: sum('files'), audio: sum('audio') }
}
