import { X } from 'lucide-react'
import { createPortal } from 'react-dom'

import { useFileActions, useFileActionState } from '@/lib/file-actions'

export function FileNotice() {
  const { controller } = useFileActions()
  const { notice, noticeHost } = useFileActionState()
  if (!notice) return null
  const content = (
    <div
      className="fixed inset-x-4 bottom-5 z-[100] mx-auto flex max-w-2xl items-start gap-3 rounded-lg border border-border bg-popover p-4 text-sm text-popover-foreground shadow-lg"
      data-file-notice=""
    >
      <div className="min-w-0 flex-1" role={notice.kind === 'error' ? 'alert' : 'status'}>
        <p className="whitespace-pre-wrap break-words">{notice.message}</p>
        {notice.kind === 'path' && (
          <p className="mt-1 select-text whitespace-pre-wrap break-all font-mono" dir="ltr">
            {notice.path}
          </p>
        )}
      </div>
      {notice.kind === 'error' && notice.retry && (
        <button
          type="button"
          className="shrink-0 underline underline-offset-4"
          onClick={notice.retry}
        >
          Retry
        </button>
      )}
      <button
        type="button"
        aria-label="Dismiss file notice"
        className="shrink-0 rounded-sm p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
        onClick={() => controller.dismissNotice()}
      >
        <X aria-hidden="true" className="size-4" />
      </button>
    </div>
  )
  return noticeHost ? createPortal(content, noticeHost) : content
}
