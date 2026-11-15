import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { FileTypeIcon } from '@/components/file-type-icon'
import type { MediaItem } from '@/lib/api.gen'

const iconCases: { type: MediaItem['file_type']; label: string; tone: string }[] = [
  { type: 'pdf', label: 'PDF', tone: 'text-red-700' },
  { type: 'document', label: 'Document', tone: 'text-blue-700' },
  { type: 'book', label: 'Book', tone: 'text-blue-700' },
  { type: 'slides', label: 'Presentation', tone: 'text-blue-700' },
  { type: 'sheet', label: 'Spreadsheet', tone: 'text-emerald-700' },
  { type: 'image', label: 'Image', tone: 'text-violet-700' },
  { type: 'audio', label: 'Audio', tone: 'text-cyan-700' },
  { type: 'video', label: 'Video', tone: 'text-pink-700' },
  { type: 'archive', label: 'Archive', tone: 'text-yellow-700' },
  { type: 'model', label: '3D model', tone: 'text-lime-700' },
  { type: 'code', label: 'Code', tone: 'text-slate-700' },
  { type: 'font', label: 'Font', tone: 'text-slate-700' },
  { type: 'program', label: 'Program', tone: 'text-orange-700' },
  { type: 'script', label: 'Script', tone: 'text-orange-700' },
  { type: 'other', label: 'File', tone: 'text-muted-foreground' },
]

test.each(iconCases)(
  'renders the accessible $type icon in its category color',
  ({ type, label, tone }) => {
    render(<FileTypeIcon type={type} />)
    const icon = screen.getByRole('img', { name: label })
    expect(icon).toHaveClass(tone)
    expect(icon.firstElementChild).toHaveAttribute('aria-hidden', 'true')
    expect(icon.querySelectorAll('svg')).toHaveLength(type === 'pdf' ? 0 : 1)
  },
)

test('uses PDF lettering and accepts layout classes without dropping its type color', () => {
  render(<FileTypeIcon type="pdf" className="size-12 rounded-xl" />)
  const icon = screen.getByRole('img', { name: 'PDF' })
  expect(icon).toHaveTextContent('PDF')
  expect(icon).toHaveClass('size-12', 'rounded-xl', 'text-red-700')
})
