import { useCallback, useRef, type RefCallback } from 'react'

import { openMedia, openPostFolder } from '@/lib/api'
import type { MediaItem, PostDetail } from '@/lib/api.gen'
import { copyText } from '@/lib/clipboard'
import { fileActionKey, type FileActionIdentity } from '@/lib/file-action-controller'
import type { FileAction } from '@/lib/file-action-types'
import { useFileActions, useFileActionState } from '@/lib/file-actions'
import { fileExecutionHint, fileNameOnDisk } from '@/lib/file-presentation'
import { canViewInBrowser, localFilePath } from '@/lib/local-file-path'
import { mediaPath } from '@/lib/media-paths'

type CommandAction = Extract<FileAction, { kind: 'command' }>

function folderLabel(system: string | null): string {
  if (system === 'macos') return 'Open the post folder in Finder'
  if (system === 'windows') return 'Open the post folder in Explorer'
  return 'Open the post folder'
}

function revealLabel(system: string | null): string {
  if (system === 'macos') return 'Show in Finder'
  if (system === 'windows') return 'Show in Explorer'
  return 'Show in folder'
}

export function useMediaFileActions(
  author: string,
  item: MediaItem,
  options?: { onOpen?: () => void },
): { actions: readonly FileAction[]; local: boolean } {
  const { controller, capabilities } = useFileActions()
  const { pending } = useFileActionState()
  const actions: FileAction[] = []
  const local = Boolean(capabilities?.open || capabilities?.reveal)
  const command = (
    action: FileActionIdentity['action'],
    label: string,
    operation: () => Promise<void>,
    hint: string | null = null,
  ): CommandAction => {
    const identity: FileActionIdentity = { author, kind: 'media', id: item.id, action }
    return {
      kind: 'command',
      id: action,
      label,
      hint,
      pending: pending.has(fileActionKey(identity)),
      run: () =>
        controller.run(identity, operation, action === 'open' ? options?.onOpen : undefined),
    }
  }
  if (capabilities?.open) {
    actions.push(
      command(
        'open',
        'Open in default app',
        () => openMedia(author, item.id, false),
        fileExecutionHint(item.file_type),
      ),
    )
  }
  if (capabilities?.reveal) {
    actions.push(
      command('reveal', revealLabel(capabilities.system), () => openMedia(author, item.id, true)),
    )
  }
  const path = local && capabilities ? localFilePath(capabilities, author, item.path) : null
  if (path !== null) {
    actions.push(
      command('copy', 'Copy path', async () => {
        const copied = await copyText(path)
        controller.showNotice({
          kind: 'path',
          path,
          message: copied ? 'Path copied' : 'Copy this path',
        })
      }),
    )
  }
  const href = mediaPath(author, item.path)
  if (capabilities && !local && canViewInBrowser(item.path)) {
    actions.push({ kind: 'link', id: 'view', label: 'View in a new tab', href, target: '_blank' })
  }
  actions.push({
    kind: 'link',
    id: 'download',
    label: 'Download a copy',
    href,
    download: fileNameOnDisk(item),
  })
  return { actions, local }
}

export function usePostFolderAction(
  author: string,
  post: Pick<PostDetail, 'id' | 'has_folder'>,
): CommandAction | null {
  const { controller, capabilities } = useFileActions()
  const { pending } = useFileActionState()
  if (!post.has_folder || !capabilities?.open || !capabilities.folders) return null
  const identity: FileActionIdentity = { author, kind: 'post', id: post.id, action: 'open' }
  return {
    kind: 'command',
    id: 'open',
    label: folderLabel(capabilities.system),
    hint: null,
    pending: pending.has(fileActionKey(identity)),
    run: () => controller.run(identity, () => openPostFolder(author, post.id)),
  }
}

/** The visible fullscreen dialog owns the single notice's accessible location. */
export function useFileNoticeHost(): RefCallback<HTMLElement> {
  const { controller } = useFileActions()
  const ownedHost = useRef<HTMLElement | null>(null)
  return useCallback(
    (host) => {
      if (!host) {
        if (ownedHost.current) controller.clearNoticeHost(ownedHost.current)
        ownedHost.current = null
        return
      }
      ownedHost.current = host
      controller.setNoticeHost(host)
      return () => {
        controller.clearNoticeHost(host)
        if (ownedHost.current === host) ownedHost.current = null
      }
    },
    [controller],
  )
}
