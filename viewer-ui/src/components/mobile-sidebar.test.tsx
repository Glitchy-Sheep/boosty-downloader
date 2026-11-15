import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useRef, useState } from 'react'
import { afterEach, expect, test, vi } from 'vitest'

import { MobileSidebar } from '@/components/mobile-sidebar'
import { useAuthorSidebar } from '@/hooks/use-author-sidebar'

afterEach(() => vi.restoreAllMocks())

function Screen({ active = true, docked = false } = {}) {
  const toggleRef = useRef<HTMLButtonElement>(null)
  const searchInput = useRef<HTMLInputElement>(null)
  const sidebar = useAuthorSidebar({ active, docked, toggleRef })
  const [text, setText] = useState('')
  return (
    <>
      <button ref={toggleRef} onClick={sidebar.toggle} disabled={!active}>
        Toggle sidebar
      </button>
      <button onClick={() => sidebar.search(searchInput)}>Search shortcut</button>
      <MobileSidebar controller={sidebar} searchInput={searchInput}>
        <input
          ref={searchInput}
          aria-label="Search posts"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return
            if (text) setText('')
            else event.currentTarget.blur()
          }}
        />
        <button onClick={sidebar.mobile.close}>Select current post</button>
      </MobileSidebar>
    </>
  )
}

test('ordinary opening focuses the sheet, row selection closes it and returns focus', async () => {
  render(<Screen />)
  const toggle = screen.getByRole('button', { name: 'Toggle sidebar' })
  fireEvent.click(toggle)
  expect(screen.getByRole('dialog', { name: 'Posts' })).toHaveFocus()
  expect(screen.getByRole('textbox')).not.toHaveFocus()
  fireEvent.click(screen.getByRole('button', { name: 'Select current post' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await waitFor(() => expect(toggle).toHaveFocus())
  fireEvent.click(toggle)
  fireEvent.click(screen.getByRole('button', { name: 'Close sidebar' }))
  await waitFor(() => expect(toggle).toHaveFocus())
})

test('search opening waits for the input and Escape clears, blurs, then dismisses', async () => {
  render(<Screen />)
  fireEvent.click(screen.getByRole('button', { name: 'Search shortcut' }))
  const input = screen.getByRole('textbox')
  expect(input).toHaveFocus()
  fireEvent.change(input, { target: { value: 'draft' } })
  fireEvent.keyDown(input, { key: 'Escape', code: 'Escape' })
  expect(input).toHaveValue('')
  expect(input).toHaveFocus()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  fireEvent.keyDown(input, { key: 'Escape', code: 'Escape' })
  expect(input).not.toHaveFocus()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

test('sheet shortcuts honor editors, modifiers and key repeat', () => {
  render(<Screen />)
  fireEvent.click(screen.getByRole('button', { name: 'Toggle sidebar' }))
  const sheet = screen.getByRole('dialog')
  fireEvent.keyDown(sheet, { code: 'BracketLeft', repeat: true })
  fireEvent.keyDown(sheet, { code: 'BracketLeft', ctrlKey: true })
  expect(sheet).toBeInTheDocument()
  fireEvent.keyDown(sheet, { code: 'Slash' })
  const input = screen.getByRole('textbox')
  expect(input).toHaveFocus()
  fireEvent.keyDown(input, { code: 'BracketLeft' })
  expect(sheet).toBeInTheDocument()
  fireEvent.keyDown(sheet, { code: 'BracketLeft' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test.each([
  { active: false, docked: false },
  { active: true, docked: true },
])('delayed close focus cannot return to an unavailable mobile control: %j', async (next) => {
  const view = render(<Screen />)
  const toggle = screen.getByRole('button', { name: 'Toggle sidebar' })
  fireEvent.click(toggle)
  const focus = vi.spyOn(toggle, 'focus')
  fireEvent.click(screen.getByRole('button', { name: 'Close sidebar' }))
  view.rerender(<Screen {...next} />)
  await act(() => new Promise((resolve) => window.setTimeout(resolve, 10)))
  expect(focus).not.toHaveBeenCalled()
  view.rerender(<Screen />)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
