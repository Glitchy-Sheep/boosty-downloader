import { afterEach, expect, test, vi } from 'vitest'

import { copyText } from '@/lib/clipboard'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  Reflect.deleteProperty(document, 'execCommand')
  document.body.replaceChildren()
})

function legacyCopy(result: boolean | Error) {
  const command = vi.fn(() => {
    if (result instanceof Error) throw result
    return result
  })
  Object.defineProperty(document, 'execCommand', { configurable: true, value: command })
  return command
}

test('prefers the Clipboard API and copies the full original value', async () => {
  const writeText = vi.fn(async () => {})
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  const command = legacyCopy(true)
  expect(await copyText('/library/автор  %2F/file.pdf')).toBe(true)
  expect(writeText).toHaveBeenCalledExactlyOnceWith('/library/автор  %2F/file.pdf')
  expect(command).not.toHaveBeenCalled()
})

test.each(['dialog', 'menu'])(
  'falls back inside the active %s, restoring focus and input selection',
  async (role) => {
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: vi.fn(async () => {
          throw new Error('Permission denied')
        }),
      },
    })
    const dialog = document.createElement('div')
    dialog.setAttribute('role', role)
    const input = document.createElement('input')
    input.value = 'selected text'
    dialog.append(input)
    document.body.append(dialog)
    input.focus()
    input.setSelectionRange(2, 7, 'backward')
    const command = legacyCopy(true)
    command.mockImplementationOnce(() => {
      const field = document.activeElement
      expect(field).toBeInstanceOf(HTMLTextAreaElement)
      expect(field?.parentElement).toBe(dialog)
      expect((field as HTMLTextAreaElement).value).toBe('/library/raw%25.pdf')
      return true
    })
    expect(await copyText('/library/raw%25.pdf')).toBe(true)
    expect(command).toHaveBeenCalledWith('copy')
    expect(document.activeElement).toBe(input)
    expect([input.selectionStart, input.selectionEnd, input.selectionDirection]).toEqual([
      2,
      7,
      'backward',
    ])
    expect(dialog.querySelector('textarea')).toBeNull()
  },
)

test('restores a document selection when the insecure-context fallback fails', async () => {
  vi.stubGlobal('navigator', {})
  const text = document.createElement('p')
  text.textContent = 'selected text'
  document.body.append(text)
  const range = document.createRange()
  range.selectNodeContents(text)
  window.getSelection()?.removeAllRanges()
  window.getSelection()?.addRange(range)
  legacyCopy(false)
  expect(await copyText('/library/file')).toBe(false)
  expect(window.getSelection()?.toString()).toBe('selected text')
  expect(document.querySelector('textarea')).toBeNull()
})

test('returns a manual-copy result when both APIs are absent or the copy command throws', async () => {
  vi.stubGlobal('navigator', {})
  expect(await copyText('/library/file')).toBe(false)
  legacyCopy(new Error('Not allowed'))
  expect(await copyText('/library/file')).toBe(false)
  expect(document.querySelector('textarea')).toBeNull()
})

test('does not restore focus to a control removed while copying', async () => {
  vi.stubGlobal('navigator', {})
  const button = document.createElement('button')
  document.body.append(button)
  button.focus()
  const focus = vi.spyOn(button, 'focus')
  const command = legacyCopy(true)
  command.mockImplementationOnce(() => {
    button.remove()
    return true
  })
  expect(await copyText('/library/file')).toBe(true)
  expect(focus).not.toHaveBeenCalled()
})

test('copies without a focused element or a document selection API', async () => {
  vi.stubGlobal('navigator', {})
  vi.spyOn(document, 'activeElement', 'get').mockReturnValue(null)
  vi.spyOn(window, 'getSelection').mockReturnValue(null)
  legacyCopy(true)
  expect(await copyText('/library/file')).toBe(true)
  expect(document.querySelector('textarea')).toBeNull()
})

test('restores text selections even when the browser reports no selection direction', async () => {
  vi.stubGlobal('navigator', {})
  const input = document.createElement('textarea')
  input.value = 'selected text'
  document.body.append(input)
  input.focus()
  input.setSelectionRange(1, 5)
  Object.defineProperty(input, 'selectionDirection', { configurable: true, value: null })
  const restore = vi.spyOn(input, 'setSelectionRange')
  legacyCopy(true)
  expect(await copyText('/library/file')).toBe(true)
  expect(restore).toHaveBeenCalledWith(1, 5, undefined)
})
