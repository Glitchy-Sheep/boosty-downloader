type TextSelection = {
  element: HTMLInputElement | HTMLTextAreaElement
  start: number | null
  end: number | null
  direction: 'forward' | 'backward' | 'none' | null
}

function activeTextSelection(element: Element | null): TextSelection | null {
  if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) return null
  return {
    element,
    start: element.selectionStart,
    end: element.selectionEnd,
    direction: element.selectionDirection,
  }
}

function copyWithTextField(text: string): boolean {
  const focused = document.activeElement
  const inputSelection = activeTextSelection(focused)
  const selection = window.getSelection()
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) =>
        selection.getRangeAt(index).cloneRange(),
      )
    : []
  const field = document.createElement('textarea')
  field.value = text
  field.setAttribute('readonly', '')
  field.setAttribute('aria-label', 'Path to copy')
  field.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;'
  // Keep the temporary field inside the active menu or dialog focus boundary.
  const host = focused instanceof Element ? focused.closest('[role="menu"], [role="dialog"]') : null
  ;(host ?? document.body).append(field)
  try {
    field.focus({ preventScroll: true })
    field.select()
    // Insecure LAN pages have no Clipboard API, but still support the legacy copy command.
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    field.remove()
    if (focused instanceof HTMLElement && focused.isConnected)
      focused.focus({ preventScroll: true })
    if (inputSelection && inputSelection.start !== null && inputSelection.end !== null) {
      inputSelection.element.setSelectionRange(
        inputSelection.start,
        inputSelection.end,
        inputSelection.direction ?? undefined,
      )
    }
    if (selection) {
      selection.removeAllRanges()
      for (const range of ranges) selection.addRange(range)
    }
  }
}

/** A false result asks the caller to expose the complete path for manual copying. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // A denied Clipboard API request can still use the page's copy command.
  }
  return copyWithTextField(text)
}
