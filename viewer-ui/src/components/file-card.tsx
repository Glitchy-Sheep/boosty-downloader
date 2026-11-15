import { createPortal } from 'react-dom'

import { FileActions } from '@/components/file-actions'
import { FileTypeIcon } from '@/components/file-type-icon'
import { useMediaFileActions } from '@/hooks/use-file-actions'
import { fileMetadata } from '@/lib/file-metadata'
import { displayFileName, fileExecutionLabel, fileNameOnDisk } from '@/lib/file-presentation'
import type { PostAttachment } from '@/lib/post-attachments'

/** Attachment cards keep their text selectable and their actions separate. */
export function FileCard({ author, attachment }: { author: string; attachment: PostAttachment }) {
  const { item } = attachment
  const { actions } = useMediaFileActions(author, item)
  const execution = fileExecutionLabel(item.file_type)
  return (
    <>
      {createPortal(<FileTypeIcon type={item.file_type} />, attachment.icon)}
      {createPortal(
        execution && <span className="attachment-execution">{execution}</span>,
        attachment.badge,
      )}
      {createPortal(fileMetadata(item), attachment.metadata)}
      {createPortal(
        <FileActions actions={actions} mode="file" label={displayFileName(fileNameOnDisk(item))} />,
        attachment.actions,
      )}
    </>
  )
}
