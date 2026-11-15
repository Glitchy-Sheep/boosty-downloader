import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Dialog } from 'radix-ui'
import { afterEach, expect, test, vi } from 'vitest'

import { FileActions } from '@/components/file-actions'
import { FileContextMenu } from '@/components/file-context-menu'
import { useFileNoticeHost, useMediaFileActions } from '@/hooks/use-file-actions'
import { createFileActionsTestApp, localFileCapabilities } from '@/test/file-actions'
import { savedVideo } from '@/test/post-fixtures'

type MenuKind = 'dropdown' | 'context'

const storedPath = 'post/сырой  %2F.pdf'
const fullPath = `/Library/автор/${storedPath}`

function CopyMenu({ menu, fullscreen }: { menu: MenuKind; fullscreen: boolean }) {
  const { actions } = useMediaFileActions('автор', { ...savedVideo, path: storedPath })
  const copy = actions.filter((action) => action.id === 'copy')
  const noticeHost = useFileNoticeHost()
  const controls =
    menu === 'dropdown' ? (
      <FileActions actions={copy} mode="menu" label="file.pdf" />
    ) : (
      <FileContextMenu actions={copy} enabled label="file.pdf">
        <button type="button">File</button>
      </FileContextMenu>
    )
  if (!fullscreen) return controls
  return (
    <Dialog.Root defaultOpen>
      <Dialog.Portal>
        <Dialog.Content aria-describedby={undefined} ref={noticeHost}>
          <Dialog.Title>Fullscreen file</Dialog.Title>
          {controls}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Reflect.deleteProperty(document, 'execCommand')
})

test.each([
  { menu: 'dropdown' as const, fullscreen: true, clipboard: 'absent', copied: true },
  { menu: 'context' as const, fullscreen: true, clipboard: 'absent', copied: true },
  { menu: 'dropdown' as const, fullscreen: false, clipboard: 'absent', copied: true },
  { menu: 'context' as const, fullscreen: false, clipboard: 'absent', copied: true },
  { menu: 'dropdown' as const, fullscreen: true, clipboard: 'denied', copied: true },
  { menu: 'context' as const, fullscreen: true, clipboard: 'absent', copied: false },
])(
  'copies from a real $menu menu with fullscreen=$fullscreen, clipboard=$clipboard and copied=$copied',
  async ({ menu, fullscreen, clipboard, copied }) => {
    const writeText = vi.fn(async () => {
      throw new Error('Clipboard permission denied')
    })
    vi.stubGlobal('navigator', clipboard === 'denied' ? { clipboard: { writeText } } : {})
    let copiedValue: string | null = null
    let copyHost: Element | null = null
    const command = vi.fn(() => {
      const field = document.activeElement
      if (!(field instanceof HTMLTextAreaElement)) return false
      copiedValue = field.value
      copyHost = field.parentElement
      return copied
    })
    Object.defineProperty(document, 'execCommand', { configurable: true, value: command })
    const { Wrapper } = createFileActionsTestApp(localFileCapabilities)
    render(<CopyMenu menu={menu} fullscreen={fullscreen} />, { wrapper: Wrapper })
    const trigger = screen.getByRole('button', {
      name: menu === 'dropdown' ? 'More for file.pdf' : 'File',
    })
    act(() => trigger.focus())
    if (menu === 'dropdown') fireEvent.keyDown(trigger, { key: 'Enter' })
    else fireEvent.contextMenu(trigger)
    const item = await screen.findByRole('menuitem', { name: 'Copy path' })
    act(() => item.focus())
    expect(item).toHaveFocus()
    expect(item.closest('[role="dialog"]')).toBeNull()
    fireEvent.keyDown(item, { key: 'Enter' })
    const notice = await screen.findByRole('status')
    expect(notice).toHaveTextContent(copied ? 'Path copied' : 'Copy this path')
    expect(notice.textContent).toContain(fullPath)
    expect(command).toHaveBeenCalledExactlyOnceWith('copy')
    expect(copiedValue).toBe(fullPath)
    expect(copyHost).not.toBeNull()
    if (clipboard === 'absent')
      expect((copyHost as Element | null)?.matches('[role="menu"]')).toBe(true)
    expect(document.querySelector('textarea')).toBeNull()
    if (fullscreen) expect(within(screen.getByRole('dialog')).getByRole('status')).toBe(notice)
    await waitFor(() => expect(trigger).toHaveFocus())
    if (clipboard === 'denied') expect(writeText).toHaveBeenCalledWith(fullPath)
  },
)
