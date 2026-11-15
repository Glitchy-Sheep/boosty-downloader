import {
  AppWindow,
  BookOpen,
  File,
  FileArchive,
  FileAxis3d,
  FileCode,
  FileImage,
  FileMusic,
  FileSpreadsheet,
  FileTerminal,
  FileText,
  FileType as FileFont,
  FileVideoCamera,
  Presentation,
  type LucideIcon,
} from 'lucide-react'

import type { MediaItem } from '@/lib/api.gen'

type FileType = MediaItem['file_type']
type ExecutionLabel = 'Program' | 'Script'
type FileExecution = { label: ExecutionLabel; hint: string }
type FilePresentation = {
  label: string
  noun: string
  icon: LucideIcon
  tone: string
  letters?: string
  execution?: FileExecution
}
export type FileNameParts = { stem: string; suffix: string }

const BLUE_TONE = 'bg-blue-500/12 text-blue-700 dark:text-blue-400'
const SLATE_TONE = 'bg-slate-500/15 text-slate-700 dark:text-slate-300'
const ORANGE_TONE = 'bg-orange-500/12 text-orange-700 dark:text-orange-400'

export const FILE_PRESENTATION: Record<FileType, FilePresentation> = {
  pdf: {
    label: 'PDF',
    noun: 'document',
    icon: FileText,
    letters: 'PDF',
    tone: 'bg-red-500/12 text-red-700 dark:text-red-400',
  },
  document: { label: 'Document', noun: 'document', icon: FileText, tone: BLUE_TONE },
  book: { label: 'Book', noun: 'book', icon: BookOpen, tone: BLUE_TONE },
  slides: { label: 'Presentation', noun: 'presentation', icon: Presentation, tone: BLUE_TONE },
  sheet: {
    label: 'Spreadsheet',
    noun: 'spreadsheet',
    icon: FileSpreadsheet,
    tone: 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-400',
  },
  image: {
    label: 'Image',
    noun: 'image',
    icon: FileImage,
    tone: 'bg-violet-500/12 text-violet-700 dark:text-violet-400',
  },
  audio: {
    label: 'Audio',
    noun: 'audio',
    icon: FileMusic,
    tone: 'bg-cyan-500/12 text-cyan-700 dark:text-cyan-400',
  },
  video: {
    label: 'Video',
    noun: 'video',
    icon: FileVideoCamera,
    tone: 'bg-pink-500/12 text-pink-700 dark:text-pink-400',
  },
  archive: {
    label: 'Archive',
    noun: 'archive',
    icon: FileArchive,
    tone: 'bg-yellow-500/15 text-yellow-700 dark:text-yellow-400',
  },
  model: {
    label: '3D model',
    noun: '3D model',
    icon: FileAxis3d,
    tone: 'bg-lime-500/12 text-lime-700 dark:text-lime-400',
  },
  code: { label: 'Code', noun: 'file', icon: FileCode, tone: SLATE_TONE },
  font: { label: 'Font', noun: 'font', icon: FileFont, tone: SLATE_TONE },
  program: {
    label: 'Program',
    noun: 'program',
    icon: AppWindow,
    tone: ORANGE_TONE,
    execution: { label: 'Program', hint: 'The program starts' },
  },
  script: {
    label: 'Script',
    noun: 'script',
    icon: FileTerminal,
    tone: ORANGE_TONE,
    execution: { label: 'Script', hint: 'The script may run' },
  },
  other: { label: 'File', noun: 'file', icon: File, tone: 'bg-muted text-muted-foreground' },
}

const DIRECTION_CONTROLS = /[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g
const LINE_AND_CONTROL_CHARACTERS = /[\p{Cc}\u2028\u2029]/gu
const MAX_VISIBLE_SUFFIX_LENGTH = 24

/** Use the stored basename without decoding or changing the filesystem path. */
export function fileNameOnDisk(item: Pick<MediaItem, 'path'>): string {
  return item.path.slice(item.path.lastIndexOf('/') + 1)
}

/** Preserve spaces while preventing controls from reordering or breaking the name. */
export function displayFileName(name: string): string {
  return name.replace(DIRECTION_CONTROLS, '').replace(LINE_AND_CONTROL_CHARACTERS, '\ufffd')
}

export function fileNameParts(name: string): FileNameParts {
  const displayName = displayFileName(name)
  // Windows ignores trailing dots and spaces when deciding the file's suffix.
  const suffixStart = displayName.replace(/[ .]+$/, '').lastIndexOf('.')
  const suffix = suffixStart > 0 ? displayName.slice(suffixStart) : ''
  if (!suffix || suffix.length > MAX_VISIBLE_SUFFIX_LENGTH || suffix.trimEnd().includes(' ')) {
    return { stem: displayName, suffix: '' }
  }
  return { stem: displayName.slice(0, suffixStart), suffix }
}

export function fileTypeLabel(type: FileType): string {
  return FILE_PRESENTATION[type].label
}

export function fileExecutionLabel(type: FileType): ExecutionLabel | null {
  return FILE_PRESENTATION[type].execution?.label ?? null
}

export function fileExecutionHint(type: FileType): string | null {
  return FILE_PRESENTATION[type].execution?.hint ?? null
}

/** Name the kind like a file manager, for example "ZIP archive" or "EXE program". */
export function fileKind(name: string, type: FileType): string {
  const suffix = fileNameParts(name)
    .suffix.replace(/[ .]+$/, '')
    .slice(1)
    .toUpperCase()
  const { noun } = FILE_PRESENTATION[type]
  return suffix ? `${suffix} ${noun}` : noun.charAt(0).toUpperCase() + noun.slice(1)
}
