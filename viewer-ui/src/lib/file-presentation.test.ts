import { expect, test } from 'vitest'

import type { MediaItem } from '@/lib/api.gen'
import {
  displayFileName,
  fileExecutionHint,
  fileExecutionLabel,
  fileKind,
  fileNameOnDisk,
  fileNameParts,
  fileTypeLabel,
} from '@/lib/file-presentation'

const typeLabels: { type: MediaItem['file_type']; label: string }[] = [
  { type: 'pdf', label: 'PDF' },
  { type: 'document', label: 'Document' },
  { type: 'book', label: 'Book' },
  { type: 'sheet', label: 'Spreadsheet' },
  { type: 'slides', label: 'Presentation' },
  { type: 'image', label: 'Image' },
  { type: 'audio', label: 'Audio' },
  { type: 'video', label: 'Video' },
  { type: 'archive', label: 'Archive' },
  { type: 'model', label: '3D model' },
  { type: 'code', label: 'Code' },
  { type: 'font', label: 'Font' },
  { type: 'program', label: 'Program' },
  { type: 'script', label: 'Script' },
  { type: 'other', label: 'File' },
]

test('takes the actual stored basename without API filename or URL decoding', () => {
  const item = { path: 'post/files/  renamed %20 +\u202efdp.exe  ', filename: 'invoice.pdf' }
  expect(fileNameOnDisk(item)).toBe('  renamed %20 +\u202efdp.exe  ')
  expect(displayFileName(fileNameOnDisk(item))).toBe('  renamed %20 +fdp.exe  ')
  expect(fileNameOnDisk({ path: 'alone.txt' })).toBe('alone.txt')
})

test('removes every directional control while preserving ordinary Unicode and spaces', () => {
  const controls = '\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
  expect(displayFileName(`  résumé  שלום${controls}.pdf  `)).toBe('  résumé  שלום.pdf  ')
  expect(displayFileName('invoice\u202efdp.exe')).toBe('invoicefdp.exe')
})

test('replaces controls and line separators with visible characters', () => {
  expect(displayFileName('a\0\t\n\r\u007f\u0085\u009f\u2028\u2029 b.pdf')).toBe('a��������� b.pdf')
})

test.each([
  { name: 'invoice.pdf.exe', stem: 'invoice.pdf', suffix: '.exe' },
  { name: 'setup.exe.  ', stem: 'setup', suffix: '.exe.  ' },
  { name: 'long name.settingcontent-ms', stem: 'long name', suffix: '.settingcontent-ms' },
  { name: '  many   spaces.txt', stem: '  many   spaces', suffix: '.txt' },
  { name: 'invoice\u202efdp.exe', stem: 'invoicefdp', suffix: '.exe' },
  { name: 'line\nname.txt', stem: 'line�name', suffix: '.txt' },
  { name: 'v1.2 (final)', stem: 'v1.2 (final)', suffix: '' },
  { name: '.exe', stem: '.exe', suffix: '' },
  { name: 'no suffix', stem: 'no suffix', suffix: '' },
  { name: '...', stem: '...', suffix: '' },
  { name: '', stem: '', suffix: '' },
])('keeps the visible suffix of $name', ({ name, stem, suffix }) => {
  expect(fileNameParts(name)).toEqual({ stem, suffix })
})

test('preserves suffixes up to 24 characters and leaves longer suffixes in the stem', () => {
  const suffix = `.${'x'.repeat(23)}`
  expect(fileNameParts(`name${suffix}`)).toEqual({ stem: 'name', suffix })
  expect(fileNameParts(`name${suffix}x`)).toEqual({ stem: `name${suffix}x`, suffix: '' })
})

test.each(typeLabels)('names the $type category', ({ type, label }) => {
  expect(fileTypeLabel(type)).toBe(label)
})

test('explains only the program and script execution categories', () => {
  expect(fileExecutionLabel('program')).toBe('Program')
  expect(fileExecutionHint('program')).toBe('The program starts')
  expect(fileExecutionLabel('script')).toBe('Script')
  expect(fileExecutionHint('script')).toBe('The script may run')
  for (const { type } of typeLabels) {
    if (type === 'program' || type === 'script') continue
    expect(fileExecutionLabel(type)).toBeNull()
    expect(fileExecutionHint(type)).toBeNull()
  }
})

test.each([
  { name: 'bundle.ZIP', type: 'archive', label: 'ZIP archive' },
  { name: 'report.pdf', type: 'pdf', label: 'PDF document' },
  { name: 'setup.exe.  ', type: 'program', label: 'EXE program' },
  { name: 'run.py', type: 'script', label: 'PY script' },
  { name: 'formula.XLSM', type: 'sheet', label: 'XLSM spreadsheet' },
  { name: 'README', type: 'other', label: 'File' },
  { name: 'model', type: 'model', label: '3D model' },
] satisfies { name: string; type: MediaItem['file_type']; label: string }[])(
  'describes $name by suffix and server-provided type',
  ({ name, type, label }) => {
    expect(fileKind(name, type)).toBe(label)
  },
)
