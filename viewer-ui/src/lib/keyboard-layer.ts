import type { KeyboardEvent } from 'react'

/** The nearest dialog or menu owns keys from its focused controls. */
export function keyboardLayer(target: EventTarget | null): Element | null {
  if (!(target instanceof Element)) return null
  return target.closest('dialog, [role="dialog"], [role="alertdialog"], [role="menu"]')
}

/** Close only the focused dialog or menu, including newly opened content. */
export function dismissLayerOnEscape(event: KeyboardEvent<HTMLElement>, dismiss: () => void): void {
  if (event.key !== 'Escape' || keyboardLayer(event.target) !== event.currentTarget) return
  event.preventDefault()
  event.stopPropagation()
  dismiss()
}
