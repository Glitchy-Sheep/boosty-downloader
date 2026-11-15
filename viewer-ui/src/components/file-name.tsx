import type { ClipboardEvent } from 'react'

import { fileNameParts } from '@/lib/file-presentation'

type FileNameProps = { name: string; wrap?: boolean }

/** Copy selected filename text without layout-generated separators. */
function copyFileName(event: ClipboardEvent<HTMLSpanElement>): void {
  const selection = event.currentTarget.ownerDocument.getSelection()
  if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return
  const range = selection.getRangeAt(0)
  if (!event.currentTarget.contains(range.commonAncestorContainer)) return
  event.clipboardData.setData('text/plain', range.cloneContents().textContent ?? '')
  event.preventDefault()
}

/** Keep a file's suffix visible without shortening a name that already fits. */
export function FileName({ name, wrap = false }: FileNameProps) {
  const { stem, suffix } = fileNameParts(name)

  if (wrap) {
    return (
      <span
        onCopy={copyFileName}
        className="file-name min-w-0 whitespace-break-spaces [overflow-wrap:anywhere]"
        title={stem + suffix}
      >
        {stem + suffix}
      </span>
    )
  }
  return (
    <span className="file-name flex min-w-0" onCopy={copyFileName}>
      <span className="flex min-w-0 overflow-hidden whitespace-pre" title={stem + suffix}>
        <span className="min-w-0 overflow-hidden text-ellipsis whitespace-pre">{stem}</span>
        <span className="shrink-0">{suffix}</span>
      </span>
    </span>
  )
}
