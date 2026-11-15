import { useQuery } from '@tanstack/react-query'
import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react'

import type { OpenerCapabilities } from '@/lib/api.gen'
import {
  createFileActionController,
  fileActionError,
  type FileActionController,
  type FileActionState,
} from '@/lib/file-action-controller'
import { openerQuery } from '@/lib/queries'

interface FileActionsContextValue {
  controller: FileActionController
  capabilities: OpenerCapabilities | undefined
}

const FileActionsContext = createContext<FileActionsContextValue | null>(null)

export function FileActionsProvider({
  children,
  controller,
}: {
  children: ReactNode
  controller?: FileActionController
}) {
  const [ownedController] = useState(createFileActionController)
  const actions = controller ?? ownedController
  const { data, error, isSuccess, refetch } = useQuery(openerQuery())
  useEffect(() => {
    if (error) {
      actions.showNotice({
        kind: 'error',
        source: 'capabilities',
        message: `File actions are unavailable. ${fileActionError(error)}`,
        retry: () => {
          void refetch()
        },
      })
    } else if (isSuccess) actions.clearCapabilitiesError()
  }, [actions, error, isSuccess, refetch])
  return createElement(
    FileActionsContext,
    { value: { controller: actions, capabilities: isSuccess ? data : undefined } },
    children,
  )
}

export function useFileActions(): FileActionsContextValue {
  const actions = useContext(FileActionsContext)
  if (!actions) throw new Error('File actions require FileActionsProvider')
  return actions
}

export function useFileActionState(): FileActionState {
  const { controller } = useFileActions()
  return useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot)
}
