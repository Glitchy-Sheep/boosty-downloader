import { createEvent, fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { FileName } from '@/components/file-name'

test('preserves literal filename text and its complete title', () => {
  const name = '<invoice & notes>.pdf'
  const { container, rerender } = render(<FileName name={name} />)
  expect(container.textContent).toBe(name)
  expect(screen.getByTitle(name).lastElementChild?.textContent).toBe('.pdf')
  expect(container.querySelector('invoice')).toBeNull()
  rerender(<FileName name="Lyrics.settingcontent-ms" />)
  expect(screen.getByTitle('Lyrics.settingcontent-ms').textContent).toBe('Lyrics.settingcontent-ms')
  expect(screen.getByTitle('Lyrics.settingcontent-ms').lastElementChild?.textContent).toBe(
    '.settingcontent-ms',
  )
})

test('keeps copied text on one line with repeated spaces and no appended execution mark', () => {
  const { container } = render(<FileName name={'  invoice\u202efdp\n  .exe'} />)
  const displayName = '  invoicefdp�  .exe'
  expect(container.textContent).toBe(displayName)
  expect(screen.getByTitle(displayName, { normalizer: (value) => value })).toHaveClass(
    'whitespace-pre',
  )
  expect(screen.queryByText('Program')).not.toBeInTheDocument()
  expect(container.querySelector('br')).toBeNull()
})

test('switches between a wrapped complete card name and a separate suffix', () => {
  const longName = `  ${'long '.repeat(30)}name\u202e\t.settingcontent-ms`
  const displayName = `  ${'long '.repeat(30)}name�.settingcontent-ms`
  const { rerender } = render(<FileName name={longName} wrap />)
  const wrapped = screen.getByTitle(displayName, { normalizer: (value) => value })
  expect(wrapped.textContent).toBe(displayName)
  expect(wrapped).toHaveClass('whitespace-break-spaces', '[overflow-wrap:anywhere]')
  expect(wrapped.children).toHaveLength(0)
  rerender(<FileName name="Lyrics.docx" />)
  expect(screen.getByTitle('Lyrics.docx').lastElementChild?.textContent).toBe('.docx')
  expect(screen.getByTitle('Lyrics.docx').textContent).toBe('Lyrics.docx')
})

test('copies the full or partial filename as plain text without a layout separator', () => {
  const { container } = render(<FileName name="Lyrics.docx" />)
  const name = container.querySelector('.file-name')!
  const box = screen.getByTitle('Lyrics.docx')
  const selection = window.getSelection()!
  const range = document.createRange()
  range.selectNodeContents(name)
  selection.removeAllRanges()
  selection.addRange(range)
  const setData = vi.fn()
  const copy = createEvent.copy(name, { clipboardData: { setData } })
  fireEvent(name, copy)
  expect(copy.defaultPrevented).toBe(true)
  expect(setData).toHaveBeenCalledWith('text/plain', 'Lyrics.docx')
  range.setStart(box.children[0]!.firstChild!, 2)
  range.setEnd(box.children[1]!.firstChild!, 3)
  fireEvent.copy(name, { clipboardData: { setData } })
  expect(setData).toHaveBeenLastCalledWith('text/plain', 'rics.do')
  selection.removeAllRanges()
})

test('leaves selections extending outside the filename to native copying', () => {
  const { container } = render(
    <div>
      <FileName name="Lyrics.docx" />
      <span>metadata</span>
    </div>,
  )
  const name = container.querySelector('.file-name')!
  const selection = window.getSelection()!
  const range = document.createRange()
  range.selectNodeContents(container)
  selection.removeAllRanges()
  selection.addRange(range)
  const setData = vi.fn()
  const copy = createEvent.copy(name, { clipboardData: { setData } })
  fireEvent(name, copy)
  expect(copy.defaultPrevented).toBe(false)
  expect(setData).not.toHaveBeenCalled()
  selection.removeAllRanges()
})

test('leaves empty and disjoint selections to native copying', () => {
  const { container } = render(<FileName name="Lyrics.docx" />)
  const name = container.querySelector('.file-name')!
  const selection = window.getSelection()!
  selection.removeAllRanges()
  const setData = vi.fn()
  fireEvent.copy(name, { clipboardData: { setData } })
  const range = document.createRange()
  range.selectNodeContents(name)
  selection.addRange(range)
  const count = vi.spyOn(selection, 'rangeCount', 'get').mockReturnValue(2)
  fireEvent.copy(name, { clipboardData: { setData } })
  count.mockRestore()
  const getSelection = vi.spyOn(document, 'getSelection').mockReturnValue(null)
  fireEvent.copy(name, { clipboardData: { setData } })
  getSelection.mockRestore()
  expect(setData).not.toHaveBeenCalled()
  selection.removeAllRanges()
})
