export type PostShortcut = 'next' | 'previous' | 'search' | 'sidebar' | 'seen' | 'favorite'

/** Physical positions keep the reading keys available on other keyboard layouts. */
export function postShortcut(code: string): PostShortcut | null {
  switch (code) {
    case 'KeyJ':
      return 'next'
    case 'KeyK':
      return 'previous'
    case 'Slash':
      return 'search'
    case 'BracketLeft':
      return 'sidebar'
    case 'KeyS':
      return 'seen'
    case 'KeyF':
      return 'favorite'
    default:
      return null
  }
}

function ownsKeyboard(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (target.closest('input, textarea, select, audio, video, [role="textbox"], [role="combobox"]'))
    return true
  const editable = target.closest('[contenteditable]')
  return editable !== null && editable.getAttribute('contenteditable')?.toLowerCase() !== 'false'
}

function isOpenOverlay(overlay: Element): boolean {
  if (overlay.matches('dialog:not([open])')) return false
  for (let element: Element | null = overlay; element; element = element.parentElement) {
    if (element.matches('[hidden], [inert], [aria-hidden="true"], [data-state="closed"]'))
      return false
    const style = window.getComputedStyle(element)
    if (style.display === 'none' || style.visibility === 'hidden') return false
  }
  return true
}

/** Editors, native playback controls, menus and dialogs retain their own keyboard actions. */
export function acceptsPostShortcut(
  event: KeyboardEvent,
  document: Document,
  owner?: Element,
): boolean {
  if (
    event.defaultPrevented ||
    event.isComposing ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.shiftKey ||
    ownsKeyboard(event.target)
  )
    return false
  return !Array.from(
    document.querySelectorAll('dialog, [role="dialog"], [role="alertdialog"], [role="menu"]'),
  ).some((overlay) => overlay !== owner && isOpenOverlay(overlay))
}
