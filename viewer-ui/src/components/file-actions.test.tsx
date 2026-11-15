import {
  act,
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { FolderOpen } from 'lucide-react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { FileActionButton, FileActions } from '@/components/file-actions'
import { FileContextMenu } from '@/components/file-context-menu'
import { TabActive } from '@/lib/author-tab'
import type { FileAction } from '@/lib/file-action-types'

const queries = new Map<string, MediaQueryList>()
const resized = new Set<ResizeObserverCallback>()
let containerWidth = 700

beforeEach(() => {
  containerWidth = 700
  vi.stubGlobal(
    'matchMedia',
    vi.fn((media: string) => {
      let query = queries.get(media)
      if (!query) {
        query = Object.assign(new EventTarget(), {
          matches: true,
          media,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
        }) as MediaQueryList
        queries.set(media, query)
      }
      return query
    }),
  )
  vi.stubGlobal(
    'ResizeObserver',
    class implements ResizeObserver {
      callback: ResizeObserverCallback
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback
        resized.add(callback)
      }
      observe() {}
      unobserve() {}
      disconnect() {
        resized.delete(this.callback)
      }
    },
  )
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    return DOMRect.fromRect({
      width: this.hasAttribute('data-file-action-container') ? containerWidth : 100,
      height: 32,
    })
  })
})

afterEach(() => {
  vi.useRealTimers()
  document.onkeydown = null
  document.onclick = null
  queries.clear()
  resized.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function fixture() {
  const open = vi.fn<() => Promise<void>>().mockResolvedValue()
  const reveal = vi.fn<() => Promise<void>>().mockResolvedValue()
  const copy = vi.fn<() => Promise<void>>().mockResolvedValue()
  const actions: FileAction[] = [
    {
      kind: 'command',
      id: 'open',
      label: 'Open in default app',
      hint: 'The script may run',
      pending: false,
      run: open,
    },
    {
      kind: 'command',
      id: 'reveal',
      label: 'Show in Finder',
      hint: null,
      pending: false,
      run: reveal,
    },
    { kind: 'command', id: 'copy', label: 'Copy path', hint: null, pending: false, run: copy },
    {
      kind: 'link',
      id: 'download',
      label: 'Download a copy',
      href: '/media/a/file.py',
      download: 'file.py',
    },
  ]
  return { actions, open, reveal, copy }
}

function row(
  actions: readonly FileAction[],
  active = true,
  mode: 'file' | 'media' | 'menu' = 'file',
) {
  return (
    <TabActive value={active}>
      <div data-file-action-container="">
        <FileActions actions={actions} mode={mode} label="file.py" />
      </div>
    </TabActive>
  )
}

function pointerClick(element: Element, detail = 1) {
  fireEvent.pointerDown(element, { button: 0, pointerId: 1, isPrimary: true })
  fireEvent.pointerUp(element, { button: 0, pointerId: 1, isPrimary: true })
  fireEvent.click(element, { detail })
}

function mediaMatch(media: string, matches: boolean) {
  const query = queries.get(media)
  if (!query) throw new Error(`Unobserved query ${media}`)
  Object.defineProperty(query, 'matches', { value: matches, configurable: true })
  act(() => {
    query.dispatchEvent(new Event('change'))
  })
}

function resize(width: number) {
  containerWidth = width
  act(() => {
    for (const callback of resized) callback([], {} as ResizeObserver)
  })
}

async function openMenu() {
  fireEvent.keyDown(screen.getByRole('button', { name: 'More for file.py' }), { key: 'Enter' })
  return screen.findByRole('menu')
}

test('file toolbar uses ordered controls, an Open divider and native download attributes', () => {
  const { actions } = fixture()
  render(row(actions))
  const toolbar = screen.getByRole('toolbar', { name: 'file.py' })
  expect(
    [...toolbar.querySelectorAll('[data-action]')].map((element) =>
      element.getAttribute('data-action'),
    ),
  ).toEqual(['open', 'reveal', 'copy', 'download'])
  expect(within(toolbar).getAllByRole('separator')).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'Open in default app' })).toHaveAttribute(
    'aria-description',
    'The script may run',
  )
  const download = screen.getByRole('link', { name: 'Download a copy' })
  expect(download).toHaveAttribute('href', '/media/a/file.py')
  expect(download).toHaveAttribute('download', 'file.py')
  expect(download).not.toHaveAttribute('target')
})

test('a toolbar has one Tab entry and arrows stay inside the toolbar', async () => {
  const outer = vi.fn()
  const { actions } = fixture()
  document.onkeydown = outer
  render(row(actions))
  const toolbar = screen.getByRole('toolbar')
  act(() => toolbar.focus())
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Open in default app' })).toHaveFocus(),
  )
  fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Show in Finder' })).toHaveFocus())
  const focusable = [...toolbar.querySelectorAll('button, a')].filter(
    (element) => element.getAttribute('tabindex') === '0',
  )
  expect(focusable).toHaveLength(1)
  expect(outer).not.toHaveBeenCalled()
})

test('double-click opens once and a new separate click is accepted', () => {
  const { actions, open } = fixture()
  render(row(actions))
  const button = screen.getByRole('button', { name: 'Open in default app' })
  pointerClick(button)
  pointerClick(button, 2)
  expect(open).toHaveBeenCalledTimes(1)
  pointerClick(button)
  expect(open).toHaveBeenCalledTimes(2)
})

test('Open rejects a release after another origin, a secondary press and a cancelled gesture', () => {
  const { actions, open } = fixture()
  render(row(actions))
  const button = screen.getByRole('button', { name: 'Open in default app' })
  fireEvent.pointerDown(document.body, { button: 0, pointerId: 1 })
  fireEvent.pointerUp(button, { button: 0, pointerId: 1 })
  fireEvent.click(button, { detail: 1 })
  fireEvent.pointerDown(button, { button: 2, pointerId: 1 })
  fireEvent.pointerUp(button, { button: 2, pointerId: 1 })
  fireEvent.click(button)
  fireEvent.pointerDown(button, { button: 0, pointerId: 1 })
  fireEvent.pointerCancel(button)
  fireEvent.pointerUp(button, { button: 0, pointerId: 1 })
  fireEvent.click(button, { detail: 1 })
  expect(open).not.toHaveBeenCalled()
  pointerClick(button)
  expect(open).toHaveBeenCalledTimes(1)
})

test('Open rejects a pointer that leaves or changes identity before its release', () => {
  const { actions, open } = fixture()
  render(row(actions))
  const button = screen.getByRole('button', { name: 'Open in default app' })
  fireEvent.pointerDown(button, { button: 0, pointerId: 1 })
  fireEvent.pointerLeave(button)
  fireEvent.pointerUp(button, { button: 0, pointerId: 1 })
  fireEvent.click(button, { detail: 1 })
  fireEvent.pointerDown(button, { button: 0, pointerId: 1 })
  fireEvent.pointerUp(button, { button: 0, pointerId: 2 })
  fireEvent.click(button, { detail: 1 })
  expect(open).not.toHaveBeenCalled()
})

test('a completed touch gesture survives pointer departure until its click', () => {
  const { actions, open } = fixture()
  render(<FileActionButton action={actions[0]!} />)
  const button = screen.getByRole('button', { name: 'Open in default app' })
  const pointer = { button: 0, pointerId: 1, pointerType: 'touch', isPrimary: true }
  fireEvent.pointerDown(button, pointer)
  fireEvent.pointerUp(button, pointer)
  fireEvent.pointerOut(button, { ...pointer, relatedTarget: null })
  fireEvent.click(button, { detail: 1 })
  expect(open).toHaveBeenCalledTimes(1)
  fireEvent.click(button, { detail: 1 })
  expect(open).toHaveBeenCalledTimes(1)
})

test.each(['Enter', ' '])('held %s prevents repeated button activation', (key) => {
  const { actions } = fixture()
  render(row(actions))
  const button = screen.getByRole('button', { name: 'Open in default app' })
  const event = createEvent.keyDown(button, { key, repeat: true })
  fireEvent(button, event)
  expect(event.defaultPrevented).toBe(true)
})

test('folding uses the row width without rounding and follows hover capability', async () => {
  const { actions } = fixture()
  const { unmount } = render(row(actions))
  resize(511.99)
  expect(screen.queryByRole('button', { name: 'Open in default app' })).not.toBeInTheDocument()
  expect(within(await openMenu()).getAllByRole('menuitem')).toHaveLength(4)
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
  resize(512)
  expect(screen.getByRole('button', { name: 'Open in default app' })).toBeVisible()
  mediaMatch('(hover: hover)', false)
  expect(screen.getByRole('button', { name: 'More for file.py' })).toBeVisible()
  mediaMatch('(hover: hover)', true)
  expect(screen.queryByRole('button', { name: 'More for file.py' })).not.toBeInTheDocument()
  unmount()
  expect(resized.size).toBe(0)
})

test('media shows Open and Reveal directly, then folds everything below 640px', async () => {
  const { actions } = fixture()
  render(row(actions, true, 'media'))
  expect(screen.getByRole('button', { name: 'Open in default app' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Show in Finder' })).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Copy path' })).not.toBeInTheDocument()
  const menu = await openMenu()
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(2)
  fireEvent.keyDown(menu, { key: 'Escape' })
  mediaMatch('(min-width: 640px)', false)
  expect(screen.queryByRole('button', { name: 'Open in default app' })).not.toBeInTheDocument()
  expect(within(await openMenu()).getAllByRole('menuitem')).toHaveLength(4)
})

test('a resize closes the folded menu and does not resurrect it on a later resize', async () => {
  const { actions } = fixture()
  render(row(actions))
  resize(400)
  await openMenu()
  resize(700)
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  resize(400)
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})

test('toolbar and menu background clicks do not reach a surrounding media surface', async () => {
  const { actions } = fixture()
  const click = vi.fn()
  document.onclick = click
  render(row(actions, true, 'menu'))
  fireEvent.click(screen.getByRole('toolbar'))
  fireEvent.click(await openMenu())
  expect(click).not.toHaveBeenCalled()
})

test('menu keys never bubble to a media viewer and held keys do not open the file', async () => {
  const { actions, open } = fixture()
  const parentKey = vi.fn()
  document.onkeydown = parentKey
  render(row(actions, true, 'menu'))
  await openMenu()
  const item = screen.getByRole('menuitem', { name: 'Open in default app' })
  fireEvent.keyDown(item, { key: 'ArrowRight' })
  fireEvent.keyDown(item, { key: 'Enter', repeat: true })
  fireEvent.keyDown(item, { key: ' ', repeat: true })
  expect(open).not.toHaveBeenCalled()
  expect(parentKey).not.toHaveBeenCalled()
  fireEvent.keyDown(item, { key: 'Enter' })
  expect(open).toHaveBeenCalledTimes(1)
  await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
})

test('menu Open requires a primary press on that item', async () => {
  const { actions, open } = fixture()
  render(row(actions, true, 'menu'))
  await openMenu()
  const item = screen.getByRole('menuitem', { name: 'Open in default app' })
  fireEvent.pointerUp(item, { button: 0, pointerId: 1 })
  expect(open).not.toHaveBeenCalled()
  expect(screen.getByRole('menu')).toBeInTheDocument()
  pointerClick(item)
  expect(open).toHaveBeenCalledTimes(1)
})

test('inactive retained panes close portals and never restore focus into hidden content', async () => {
  const { actions } = fixture()
  const { rerender } = render(row(actions, true, 'menu'))
  await openMenu()
  const trigger = screen.getByRole('button', { name: 'More for file.py', hidden: true })
  const focus = vi.spyOn(trigger, 'focus')
  rerender(row(actions, false, 'menu'))
  await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
  expect(focus).not.toHaveBeenCalled()
  rerender(row(actions, true, 'menu'))
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})

test('identity replacement unmounts a menu without restoring its stale trigger', async () => {
  const { actions } = fixture()
  const { rerender } = render(
    <FileActions key="first" actions={actions} label="file.py" mode="menu" />,
  )
  await openMenu()
  const focus = vi.spyOn(
    screen.getByRole('button', { name: 'More for file.py', hidden: true }),
    'focus',
  )
  rerender(<FileActions key="second" actions={actions} label="other.py" mode="menu" />)
  await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
  expect(focus).not.toHaveBeenCalled()
})

test('empty capabilities render no control and later actions get the current width', () => {
  const { actions } = fixture()
  const { rerender } = render(row([]))
  expect(screen.queryByRole('toolbar')).not.toBeInTheDocument()
  rerender(row(actions))
  expect(screen.getByRole('button', { name: 'Open in default app' })).toBeVisible()
})

test('pending commands are disabled and descriptor updates retain an open menu', async () => {
  const { actions, open } = fixture()
  const { rerender } = render(row(actions, true, 'menu'))
  await openMenu()
  const pending = actions.map((action) =>
    action.kind === 'command' ? { ...action, pending: true } : action,
  )
  rerender(row(pending, true, 'menu'))
  const item = screen.getByRole('menuitem', { name: 'Open in default app' })
  expect(item).toHaveAttribute('aria-disabled', 'true')
  fireEvent.click(item)
  expect(open).not.toHaveBeenCalled()
  expect(screen.getByRole('menu')).toBeInTheDocument()
})

test('remote View and Download remain native links without local commands', async () => {
  const actions: FileAction[] = [
    {
      kind: 'link',
      id: 'view',
      label: 'View in a new tab',
      href: '/media/a/file.pdf',
      target: '_blank',
    },
    {
      kind: 'link',
      id: 'download',
      label: 'Download',
      href: '/media/a/file.pdf',
      download: 'file.pdf',
    },
  ]
  render(row(actions, true, 'menu'))
  await openMenu()
  const view = screen.getByRole('menuitem', { name: 'View in a new tab' })
  expect(view.tagName).toBe('A')
  expect(view).toHaveAttribute('target', '_blank')
  expect(view).toHaveAttribute('rel', 'noreferrer')
  expect(screen.queryByRole('menuitem', { name: /Open/ })).not.toBeInTheDocument()
})

test('a browser View link in a toolbar preserves native activation', () => {
  const actions: FileAction[] = [
    { kind: 'link', id: 'view', label: 'View in a new tab', href: '#view', target: '_blank' },
  ]
  render(row(actions))
  const link = screen.getByRole('link', { name: 'View in a new tab' })
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noreferrer')
  const click = createEvent.click(link)
  fireEvent(link, click)
  expect(click.defaultPrevented).toBe(false)
})

test('a file toolbar uses its immediate parent when no explicit row container exists', async () => {
  const { actions } = fixture()
  render(<FileActions actions={actions} mode="file" label="file.py" />)
  expect(screen.queryByRole('button', { name: 'Open in default app' })).not.toBeInTheDocument()
  expect(within(await openMenu()).getAllByRole('menuitem')).toHaveLength(4)
})

test('detached controls stay folded without a measurable container', () => {
  const { actions } = fixture()
  const container = document.createDocumentFragment()
  render(<FileActions actions={actions} mode="file" label="file.py" />, { container })
  expect(container.querySelector('[aria-label="More for file.py"]')).not.toBeNull()
  expect(container.querySelector('[data-action="open"]')).toBeNull()
})

function context(actions: FileAction[], enabled = true, active = true) {
  return (
    <TabActive value={active}>
      <FileContextMenu actions={actions} enabled={enabled} label="file.py">
        <div data-testid="row">
          <span>File</span>
          <a href="/post">Post</a>
        </div>
      </FileContextMenu>
    </TabActive>
  )
}

test('context menus show the same action order and guard a dragged right-click release', async () => {
  const { actions, open } = fixture()
  render(context(actions))
  fireEvent.contextMenu(screen.getByTestId('row'), { clientX: 30, clientY: 40 })
  const menu = await screen.findByRole('menu', { name: 'file.py' })
  expect(
    within(menu)
      .getAllByRole('menuitem')
      .map((item) => item.getAttribute('data-action')),
  ).toEqual(['open', 'reveal', 'copy', 'download'])
  const item = within(menu).getAllByRole('menuitem')[0]!
  fireEvent.pointerUp(item, { button: 2, pointerId: 1 })
  expect(open).not.toHaveBeenCalled()
  pointerClick(item)
  expect(open).toHaveBeenCalledTimes(1)
})

test('nested links retain native context menus without cancelling browser default', () => {
  const { actions } = fixture()
  render(context(actions))
  const link = screen.getByRole('link', { name: 'Post' })
  const event = createEvent.contextMenu(link)
  fireEvent(link, event)
  expect(event.defaultPrevented).toBe(false)
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})

test.each([
  { id: 'download' as const, pointerType: 'mouse' },
  { id: 'download' as const, pointerType: 'touch' },
  { id: 'view' as const, pointerType: 'mouse' },
  { id: 'view' as const, pointerType: 'touch' },
])('a nested $id action preserves native $pointerType activation', ({ id, pointerType }) => {
  const action: FileAction = { kind: 'link', id, label: 'File action', href: '#file' }
  render(
    <FileContextMenu actions={[action]} enabled label="file.py">
      <div data-file-action-container="">
        <FileActions actions={[action]} mode="file" label="file.py" />
      </div>
    </FileContextMenu>,
  )
  const link = screen.getByRole('link', { name: 'File action' })
  const pointer = { button: 0, pointerId: 1, pointerType, isPrimary: true }
  const press = createEvent.pointerDown(link, pointer)
  fireEvent(link, press)
  expect(press.defaultPrevented).toBe(false)
  fireEvent.pointerUp(link, pointer)
  if (pointerType === 'touch') fireEvent.pointerOut(link, { ...pointer, relatedTarget: null })
  const click = createEvent.click(link, { detail: 1 })
  fireEvent(link, click)
  expect(click.defaultPrevented).toBe(false)
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})

test('a link long press leaves target handlers and browser defaults intact', async () => {
  const { actions } = fixture()
  const pointerDown = vi.fn()
  vi.useFakeTimers()
  render(
    <FileContextMenu actions={actions} enabled label="file.py">
      <div data-testid="row">
        <a href="/post" onPointerDown={pointerDown}>
          <span>Post</span>
        </a>
      </div>
    </FileContextMenu>,
  )
  const target = screen.getByText('Post')
  const press = createEvent.pointerDown(target, { pointerType: 'touch', pointerId: 1, button: 0 })
  fireEvent(target, press)
  expect(pointerDown).toHaveBeenCalledTimes(1)
  expect(press.defaultPrevented).toBe(false)
  expect(screen.getByTestId('row').style).toMatchObject({ WebkitTouchCallout: 'default' })
  await act(() => vi.advanceTimersByTimeAsync(750))
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  fireEvent.pointerUp(target, { pointerType: 'touch', pointerId: 1, button: 0 })
  fireEvent.contextMenu(screen.getByTestId('row'))
  expect(screen.getByRole('menu')).toBeInTheDocument()
})

test.each([
  { enabled: false, active: true },
  { enabled: true, active: false },
])('unavailable context menu preserves browser behavior: %j', ({ enabled, active }) => {
  const { actions } = fixture()
  render(context(actions, enabled, active))
  const event = createEvent.contextMenu(screen.getByTestId('row'))
  fireEvent(screen.getByTestId('row'), event)
  expect(event.defaultPrevented).toBe(false)
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})

test('context portals close on deactivation without stale focus restoration', async () => {
  const { actions } = fixture()
  const { rerender } = render(context(actions))
  const link = screen.getByRole('link', { name: 'Post' })
  act(() => link.focus())
  fireEvent.contextMenu(screen.getByTestId('row'))
  await screen.findByRole('menu')
  const focus = vi.spyOn(link, 'focus')
  rerender(context(actions, true, false))
  await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
  expect(focus).not.toHaveBeenCalled()
  rerender(context(actions))
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})

test('context menu background clicks and arrows stay local, and Escape returns focus', async () => {
  const { actions } = fixture()
  const click = vi.fn()
  const key = vi.fn()
  document.onclick = click
  document.onkeydown = key
  render(context(actions))
  const link = screen.getByRole('link', { name: 'Post' })
  act(() => link.focus())
  fireEvent.contextMenu(screen.getByTestId('row'))
  const menu = await screen.findByRole('menu')
  fireEvent.click(menu)
  fireEvent.keyDown(menu, { key: 'ArrowRight' })
  expect(click).not.toHaveBeenCalled()
  expect(key).not.toHaveBeenCalled()
  fireEvent.keyDown(menu, { key: 'Escape' })
  await waitFor(() => expect(link).toHaveFocus())
})

test('explicit activity overrides a retained tab context', () => {
  const { actions } = fixture()
  render(
    <TabActive value={false}>
      <FileActions actions={actions} label="file.py" mode="menu" active />
      <FileContextMenu actions={actions} enabled active label="row">
        <div data-testid="row" />
      </FileContextMenu>
    </TabActive>,
  )
  expect(screen.getByRole('button', { name: 'More for file.py' })).toBeVisible()
  fireEvent.contextMenu(screen.getByTestId('row'))
  expect(screen.getByRole('menu', { name: 'row' })).toBeInTheDocument()
})

test('a standalone folder action shares guards and provides its own tooltip context', async () => {
  const { actions, open } = fixture()
  const action = actions[0]!
  const { rerender } = render(<FileActionButton action={action} icon={FolderOpen} />)
  const button = screen.getByRole('button', { name: 'Open in default app' })
  expect(button.querySelector('svg')).toHaveClass('lucide-folder-open')
  fireEvent.focus(button)
  expect(await screen.findByRole('tooltip')).toHaveTextContent('The script may run')
  pointerClick(button)
  pointerClick(button, 2)
  expect(open).toHaveBeenCalledTimes(1)
  rerender(<FileActionButton action={action} icon={FolderOpen} active={false} />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
})

test('touch long press opens local actions, while a link keeps the browser long press', async () => {
  const { actions } = fixture()
  vi.useFakeTimers()
  render(context(actions))
  fireEvent.pointerDown(screen.getByRole('link', { name: 'Post' }), {
    pointerType: 'touch',
    pointerId: 1,
    button: 0,
  })
  await act(() => vi.advanceTimersByTimeAsync(750))
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  fireEvent.pointerDown(screen.getByTestId('row'), {
    pointerType: 'touch',
    pointerId: 2,
    button: 0,
  })
  await act(() => vi.advanceTimersByTimeAsync(750))
  expect(screen.getByRole('menu')).toBeInTheDocument()
})

test('deactivating during a long press cancels the pending context menu', async () => {
  const { actions } = fixture()
  vi.useFakeTimers()
  const { rerender } = render(context(actions))
  fireEvent.pointerDown(screen.getByTestId('row'), {
    pointerType: 'touch',
    pointerId: 1,
    button: 0,
  })
  rerender(context(actions, true, false))
  await act(() => vi.advanceTimersByTimeAsync(750))
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})
