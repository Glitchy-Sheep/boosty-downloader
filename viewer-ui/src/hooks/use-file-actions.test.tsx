import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { StrictMode, type ReactNode } from 'react'
import { afterEach, assert, expect, test, vi } from 'vitest'

import { FileNotice } from '@/components/file-notice'
import {
  useFileNoticeHost,
  useMediaFileActions,
  usePostFolderAction,
} from '@/hooks/use-file-actions'
import type { MediaItem, OpenerCapabilities } from '@/lib/api.gen'
import { createFileActionController } from '@/lib/file-action-controller'
import type { FileAction } from '@/lib/file-action-types'
import { FileActionsProvider, useFileActions } from '@/lib/file-actions'
import { createQueryClient, openerQuery } from '@/lib/queries'
import { savedPost, savedVideo } from '@/test/post-fixtures'

const localCapabilities: OpenerCapabilities = {
  open: true,
  reveal: true,
  folders: true,
  root: '/Library',
  sep: '/',
  system: 'macos',
}
const remoteCapabilities: OpenerCapabilities = {
  open: false,
  reveal: false,
  folders: false,
  root: null,
  sep: '/',
  system: null,
}

afterEach(() => {
  vi.unstubAllGlobals()
  Reflect.deleteProperty(document, 'execCommand')
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function requestCapabilities(capabilities: OpenerCapabilities) {
  const request = vi.fn<typeof fetch>().mockImplementation(async (_input, init) => {
    return init?.method === 'POST'
      ? new Response(null, { status: 204 })
      : Response.json(capabilities)
  })
  vi.stubGlobal('fetch', request)
  return request
}

function testApp() {
  const client = createQueryClient()
  const controller = createFileActionController()
  function Wrapper({ children }: { children?: ReactNode }) {
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

function command(actions: readonly FileAction[], id: 'open' | 'reveal' | 'copy') {
  const action = actions.find((candidate) => candidate.id === id)
  assert.isDefined(action)
  assert(action.kind === 'command')
  return action
}

test('starts one capability request across consumers and StrictMode, offering only Download until it resolves', async () => {
  const reply = deferred<Response>()
  const request = vi.fn<typeof fetch>().mockReturnValue(reply.promise)
  vi.stubGlobal('fetch', request)
  const { Wrapper, client } = testApp()
  const result = renderHook(
    () => {
      const first = useMediaFileActions('studio', savedVideo)
      const second = useMediaFileActions('studio', { ...savedVideo, id: 'another' })
      return { first, second }
    },
    {
      wrapper: ({ children }) => (
        <StrictMode>
          <Wrapper>{children}</Wrapper>
        </StrictMode>
      ),
    },
  )
  expect(request).toHaveBeenCalledTimes(1)
  expect(result.result.current.first.actions.map((action) => action.id)).toEqual(['download'])
  expect(result.result.current.first.local).toBe(false)
  await act(async () => {
    reply.resolve(Response.json(localCapabilities))
  })
  await waitFor(() => expect(result.result.current.first.local).toBe(true))
  expect(result.result.current.first.actions.map((action) => action.id)).toEqual([
    'open',
    'reveal',
    'copy',
    'download',
  ])
  expect(result.result.current.second.actions).toHaveLength(4)
  result.unmount()
  const remount = renderHook(() => useMediaFileActions('other', savedVideo), { wrapper: Wrapper })
  expect(remount.result.current.local).toBe(true)
  expect(request).toHaveBeenCalledTimes(1)
  expect(client.getQueryData(openerQuery().queryKey)).toEqual(localCapabilities)
})

test('keeps capabilities separate across app origins', async () => {
  const request = requestCapabilities(localCapabilities)
  const client = createQueryClient()
  await client.fetchQuery(openerQuery('http://localhost:8314'))
  request.mockResolvedValueOnce(Response.json(remoteCapabilities))
  await client.fetchQuery(openerQuery('http://machine.local:8314'))
  expect(request).toHaveBeenCalledTimes(2)
  expect(client.getQueryData(openerQuery('http://localhost:8314').queryKey)).toEqual(
    localCapabilities,
  )
  expect(client.getQueryData(openerQuery('http://machine.local:8314').queryKey)).toEqual(
    remoteCapabilities,
  )
})

test('leaves reading available on capability failure and retries from a persistent notice', async () => {
  const request = vi.fn<typeof fetch>().mockRejectedValue(new Error('Connection lost'))
  vi.stubGlobal('fetch', request)
  const { Wrapper } = testApp()
  const { result } = renderHook(() => useMediaFileActions('studio', savedVideo), {
    wrapper: Wrapper,
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost')
  expect(result.current.actions.map((action) => action.id)).toEqual(['download'])
  request.mockResolvedValueOnce(Response.json(localCapabilities))
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(result.current.local).toBe(true))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(request).toHaveBeenCalledTimes(2)
})

test.each([
  {
    capabilities: localCapabilities,
    ids: ['open', 'reveal', 'copy', 'download'],
    reveal: 'Show in Finder',
  },
  {
    capabilities: { ...localCapabilities, system: 'windows' as const },
    ids: ['open', 'reveal', 'copy', 'download'],
    reveal: 'Show in Explorer',
  },
  {
    capabilities: { ...localCapabilities, system: 'linux' as const },
    ids: ['open', 'reveal', 'copy', 'download'],
    reveal: 'Show in folder',
  },
  {
    capabilities: {
      ...localCapabilities,
      system: 'android' as const,
      reveal: false,
      folders: false,
    },
    ids: ['open', 'copy', 'download'],
    reveal: undefined,
  },
  {
    capabilities: { ...localCapabilities, open: false },
    ids: ['reveal', 'copy', 'download'],
    reveal: 'Show in Finder',
  },
  {
    capabilities: { ...localCapabilities, root: null },
    ids: ['open', 'reveal', 'download'],
    reveal: 'Show in Finder',
  },
  { capabilities: remoteCapabilities, ids: ['view', 'download'], reveal: undefined },
])(
  'honors independent capability flags and system labels: $ids $reveal',
  async ({ capabilities, ids, reveal }) => {
    requestCapabilities(capabilities)
    const { Wrapper } = testApp()
    const { result } = renderHook(() => useMediaFileActions('studio', savedVideo), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.actions.map((action) => action.id)).toEqual(ids))
    expect(result.current.actions.find((action) => action.id === 'reveal')?.label).toBe(reveal)
  },
)

test.each(['post/file.html', 'post/file.svg', 'post/script.js', 'post/name:part.pdf'])(
  'offers only Download for remote active or non-inline content: %s',
  async (path) => {
    requestCapabilities(remoteCapabilities)
    const { Wrapper, client } = testApp()
    const { result } = renderHook(
      () => useMediaFileActions('studio', { ...savedVideo, path, file_type: 'image' }),
      { wrapper: Wrapper },
    )
    await waitFor(() =>
      expect(client.getQueryData(openerQuery().queryKey)).toEqual(remoteCapabilities),
    )
    expect(result.current.actions.map((action) => action.id)).toEqual(['download'])
    expect(result.current.local).toBe(false)
  },
)

test('uses stored paths for links, and explanatory hints only for Open', async () => {
  requestCapabilities(localCapabilities)
  const { Wrapper } = testApp()
  const file: MediaItem = {
    ...savedVideo,
    path: 'post/raw  %2F.exe',
    filename: 'Display name.pdf',
    file_type: 'program' as const,
  }
  const { result, rerender } = renderHook(
    ({ item }: { item: MediaItem }) => useMediaFileActions('автор %', item),
    { wrapper: Wrapper, initialProps: { item: file } },
  )
  await waitFor(() => expect(result.current.local).toBe(true))
  expect(command(result.current.actions, 'open').hint).toBe('The program starts')
  expect(command(result.current.actions, 'reveal').hint).toBeNull()
  expect(result.current.actions.at(-1)).toMatchObject({
    kind: 'link',
    href: '/media/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%25/post/raw%20%20%252F.exe',
    download: 'raw  %2F.exe',
  })
  rerender({ item: { ...file, file_type: 'script' } })
  expect(command(result.current.actions, 'open').hint).toBe('The script may run')
})

test('pauses only an accepted Open, deduplicates shared controls and releases pending on failure', async () => {
  const request = requestCapabilities(localCapabilities)
  const { Wrapper } = testApp()
  const onOpen = vi.fn()
  const { result } = renderHook(
    () => ({
      first: useMediaFileActions('studio', savedVideo, { onOpen }),
      second: useMediaFileActions('studio', savedVideo, { onOpen }),
    }),
    { wrapper: Wrapper },
  )
  await waitFor(() => expect(result.current.first.local).toBe(true))
  const reply = deferred<Response>()
  request.mockReturnValueOnce(reply.promise)
  let running!: Promise<void>
  act(() => {
    running = command(result.current.first.actions, 'open').run()
  })
  await act(() => command(result.current.second.actions, 'open').run())
  expect(onOpen).toHaveBeenCalledTimes(1)
  expect(command(result.current.first.actions, 'open').pending).toBe(true)
  await act(async () => {
    reply.resolve(
      Response.json(
        { error: { code: 'open_failed', message: 'No application for this file.' } },
        { status: 409 },
      ),
    )
    await running
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('No application for this file.')
  expect(command(result.current.second.actions, 'open').pending).toBe(false)
  await act(() => command(result.current.first.actions, 'reveal').run())
  expect(onOpen).toHaveBeenCalledTimes(1)
  expect(request.mock.calls.filter((call) => call[1]?.method === 'POST')).toHaveLength(2)
})

test.each([true, false])(
  'shows the complete raw path when clipboard success is %s',
  async (copied) => {
    requestCapabilities(localCapabilities)
    const writeText = vi.fn(async () => {
      if (!copied) throw new Error('Not permitted')
    })
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const { Wrapper } = testApp()
    const onOpen = vi.fn()
    const { result } = renderHook(
      () =>
        useMediaFileActions(
          'автор',
          { ...savedVideo, path: 'post/raw  %2F.pdf', filename: 'Other name' },
          { onOpen },
        ),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.local).toBe(true))
    await act(() => command(result.current.actions, 'copy').run())
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent(copied ? 'Path copied' : 'Copy this path')
    expect(status.textContent).toContain('/Library/автор/post/raw  %2F.pdf')
    expect(writeText).toHaveBeenCalledWith('/Library/автор/post/raw  %2F.pdf')
    expect(onOpen).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss file notice' }))
    expect(screen.queryByRole('status')).toBeNull()
  },
)

test.each([
  { capabilities: localCapabilities, hasFolder: true, label: 'Open the post folder in Finder' },
  {
    capabilities: { ...localCapabilities, system: 'windows' as const },
    hasFolder: true,
    label: 'Open the post folder in Explorer',
  },
  {
    capabilities: { ...localCapabilities, system: 'linux' as const },
    hasFolder: true,
    label: 'Open the post folder',
  },
  { capabilities: localCapabilities, hasFolder: false, label: null },
  { capabilities: { ...localCapabilities, open: false }, hasFolder: true, label: null },
  { capabilities: { ...localCapabilities, folders: false }, hasFolder: true, label: null },
])(
  'shows folders only when supported and present: $label',
  async ({ capabilities, hasFolder, label }) => {
    const request = requestCapabilities(capabilities)
    const { Wrapper, client } = testApp()
    const { result } = renderHook(
      () => usePostFolderAction('studio', { ...savedPost, has_folder: hasFolder }),
      { wrapper: Wrapper },
    )
    expect(result.current).toBeNull()
    await waitFor(() => expect(client.getQueryData(openerQuery().queryKey)).toEqual(capabilities))
    if (!label) {
      expect(result.current).toBeNull()
      return
    }
    await waitFor(() => expect(result.current?.label).toBe(label))
    assert.isNotNull(result.current)
    await act(result.current.run)
    expect(request).toHaveBeenLastCalledWith(
      '/api/authors/studio/posts/first-post/open',
      expect.objectContaining({ body: '{}', method: 'POST' }),
    )
  },
)

function NoticeHost({ name }: { name: string }) {
  const ref = useFileNoticeHost()
  return <section role="dialog" aria-label={name} ref={ref} />
}

test('keeps one plain-text notice inside the newest dialog and survives old-host cleanup', () => {
  requestCapabilities(localCapabilities)
  const { Wrapper, controller } = testApp()
  const view = render(
    <Wrapper>
      <NoticeHost key="older" name="Older" />
      <NoticeHost key="current" name="Current" />
    </Wrapper>,
  )
  act(() => {
    controller.showNotice({ kind: 'error', message: '<script>system error</script>' })
  })
  const dialog = screen.getByRole('dialog', { name: 'Current' })
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(within(dialog).getByRole('alert')).toHaveTextContent('<script>system error</script>')
  expect(dialog.querySelector('script')).toBeNull()
  view.rerender(
    <Wrapper>
      <NoticeHost key="current" name="Current" />
    </Wrapper>,
  )
  expect(
    within(screen.getByRole('dialog', { name: 'Current' })).getByRole('alert'),
  ).toHaveTextContent('system error')
  view.rerender(<Wrapper />)
  expect(screen.getByRole('alert')).toHaveTextContent('system error')
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss file notice' }))
  expect(screen.queryByRole('alert')).toBeNull()
})

test('reports a delayed native failure even after its initiating pane unmounts', async () => {
  const request = requestCapabilities(localCapabilities)
  const { Wrapper } = testApp()
  function Control() {
    const { actions } = useMediaFileActions('studio', savedVideo)
    const action = actions.find((candidate) => candidate.id === 'open')
    return action?.kind === 'command' ? (
      <button
        onClick={() => {
          void action.run()
        }}
      >
        Open
      </button>
    ) : null
  }
  const view = render(
    <Wrapper>
      <Control />
    </Wrapper>,
  )
  const open = await screen.findByRole('button', { name: 'Open' })
  const reply = deferred<Response>()
  request.mockReturnValueOnce(reply.promise)
  fireEvent.click(open)
  view.rerender(<Wrapper />)
  await act(async () => {
    reply.reject(new Error('System unavailable'))
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('System unavailable')
})

test('requires an explicit application service provider', () => {
  expect(() => renderHook(useFileActions)).toThrow('File actions require FileActionsProvider')
})

test('notice refs support null cleanup without clearing a newer host', () => {
  requestCapabilities(localCapabilities)
  const { Wrapper, controller } = testApp()
  const { result } = renderHook(useFileNoticeHost, { wrapper: Wrapper })
  const older = document.createElement('div')
  const newer = document.createElement('div')
  let cleanup: ReturnType<typeof result.current>
  act(() => {
    cleanup = result.current(older)
  })
  act(() => {
    result.current(newer)
  })
  act(() => {
    if (typeof cleanup === 'function') cleanup()
  })
  expect(controller.getSnapshot().noticeHost).toBe(newer)
  act(() => {
    result.current(null)
  })
  expect(controller.getSnapshot().noticeHost).toBeNull()
  act(() => {
    result.current(null)
  })
})

test('owns one independent action controller for each application provider', async () => {
  requestCapabilities(localCapabilities)
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <FileActionsProvider>{children}</FileActionsProvider>
      </QueryClientProvider>
    )
  }
  const first = renderHook(useFileActions, { wrapper: Wrapper })
  const second = renderHook(useFileActions, { wrapper: Wrapper })
  expect(first.result.current.controller).not.toBe(second.result.current.controller)
  const owned = first.result.current.controller
  await waitFor(() => expect(first.result.current.capabilities).toEqual(localCapabilities))
  expect(first.result.current.controller).toBe(owned)
})
