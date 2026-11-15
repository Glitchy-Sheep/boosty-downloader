import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'

import { FileNotice } from '@/components/file-notice'
import type { OpenerCapabilities } from '@/lib/api.gen'
import { createFileActionController } from '@/lib/file-action-controller'
import { FileActionsProvider } from '@/lib/file-actions'
import { PlayerProvider } from '@/lib/player'
import { createQueryClient, openerQuery } from '@/lib/queries'

export const localFileCapabilities: OpenerCapabilities = {
  open: true,
  reveal: true,
  folders: true,
  root: '/Library',
  sep: '/',
  system: 'macos',
}

export const remoteFileCapabilities: OpenerCapabilities = {
  open: false,
  reveal: false,
  folders: false,
  root: null,
  sep: '/',
  system: null,
}

export function createFileActionsTestApp(
  capabilities: OpenerCapabilities = remoteFileCapabilities,
  client = createQueryClient(),
) {
  client.setQueryData(openerQuery().queryKey, capabilities)
  const controller = createFileActionController()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <FileActionsProvider controller={controller}>
          {children}
          <FileNotice />
        </FileActionsProvider>
      </QueryClientProvider>
    )
  }
  return { client, controller, Wrapper }
}

export function renderWithFileActions(element: ReactElement) {
  return render(element, { wrapper: createFileActionsTestApp().Wrapper })
}

export function renderWithMediaActions(element: ReactElement) {
  const { Wrapper } = createFileActionsTestApp()
  return render(element, {
    wrapper: ({ children }) => (
      <Wrapper>
        <PlayerProvider>{children}</PlayerProvider>
      </Wrapper>
    ),
  })
}
