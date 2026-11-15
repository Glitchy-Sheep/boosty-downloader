import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { dismissLayerOnEscape, keyboardLayer } from '@/lib/keyboard-layer'

test('targets outside a dialog or menu have no keyboard layer', () => {
  expect(keyboardLayer(null)).toBeNull()
  expect(keyboardLayer(document)).toBeNull()
  expect(keyboardLayer(document.createElement('button'))).toBeNull()
  const dialog = document.createElement('dialog')
  const button = document.createElement('button')
  dialog.append(button)
  expect(keyboardLayer(button)).toBe(dialog)
})

test.each(['dialog', 'alertdialog', 'menu'] as const)(
  'Escape closes only the focused %s even when its parent has protected itself',
  (role) => {
    const parent = vi.fn()
    const nested = vi.fn()
    const bubble = vi.fn()
    render(
      <div
        role="dialog"
        aria-label="Posts"
        onKeyDownCapture={(event) => {
          event.preventDefault()
          dismissLayerOnEscape(event, parent)
        }}
      >
        <div
          role={role}
          aria-label="Nested layer"
          onKeyDownCapture={(event) => dismissLayerOnEscape(event, nested)}
        >
          <button onKeyDown={bubble}>Nested action</button>
        </div>
      </div>,
    )
    const action = screen.getByRole('button', { name: 'Nested action' })
    fireEvent.keyDown(action, { key: 'Enter' })
    expect(parent).not.toHaveBeenCalled()
    expect(nested).not.toHaveBeenCalled()
    bubble.mockClear()
    fireEvent.keyDown(action, { key: 'Escape' })
    expect(parent).not.toHaveBeenCalled()
    expect(nested).toHaveBeenCalledOnce()
    expect(bubble).not.toHaveBeenCalled()
  },
)
