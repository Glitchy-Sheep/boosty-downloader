import {
  act,
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { StrictMode, type ComponentProps } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { PostBody } from '@/components/post-body'
import type { MediaItem } from '@/lib/api.gen'
import { TabActive } from '@/lib/author-tab'
import { mediaPath } from '@/lib/media-paths'
import { createFileActionsTestApp, localFileCapabilities } from '@/test/file-actions'
import { savedVideo } from '@/test/post-fixtures'

const file: MediaItem = {
  ...savedVideo,
  id: 'attachment-id',
  kind: 'files',
  file_type: 'script',
  path: 'first-post/résumé  100%20.py',
  title: 'Authored description',
  filename: 'metadata-filename',
  size: 2000,
}
const defaults = {
  author: 'studio',
  postId: file.post_id,
  media: [file, savedVideo],
  query: undefined,
  onClearSearch: vi.fn(),
  savePosition: vi.fn(async () => {}),
  onNavigate: vi.fn(),
}
let width = 700

function markup(item = file): string {
  return `<p>Saved prose</p><div class="attachments"><a class="attachment" href="${mediaPath('studio', item.path)}"><span class="attachment-name">Authored description</span><span class="attachment-meta">Saved facts</span></a></div><video controls src="${mediaPath('studio', savedVideo.path)}"></video><audio controls src="/unknown.wav"></audio><img src="/drawing.jpg" alt="Drawing">`
}

function body(props: Partial<ComponentProps<typeof PostBody>> = {}, active = true) {
  return (
    <TabActive value={active}>
      <PostBody {...defaults} html={markup()} {...props} />
    </TabActive>
  )
}

beforeEach(() => {
  width = 700
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
  vi.stubGlobal('matchMedia', (media: string) => ({
    matches: true,
    media,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    return DOMRect.fromRect({
      width: this.hasAttribute('data-file-action-container') ? width : 100,
      height: 32,
    })
  })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
  HTMLElement.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test('keeps actual disk names searchable, generated controls excluded, and resumed players intact', async () => {
  const { Wrapper } = createFileActionsTestApp(localFileCapabilities)
  const { container, rerender } = render(body({ query: 'résumé' }), { wrapper: Wrapper })
  const card = container.querySelector<HTMLElement>('[data-file-card]')!
  const name = card.querySelector('.file-name')!
  const video = container.querySelector('video')!
  const audio = container.querySelector('audio')!
  const open = within(card).getByRole('button', { name: 'Open in default app' })
  const pause = vi.fn()
  video.addEventListener('pause', pause)
  Object.defineProperties(video, {
    duration: { configurable: true, value: 100 },
    readyState: { configurable: true, value: 1 },
  })
  fireEvent.loadedMetadata(video)
  expect(video.currentTime).toBe(20)
  expect(screen.getByRole('button', { name: 'Start over' })).toBeInTheDocument()
  expect(card.tagName).toBe('DIV')
  expect(card).not.toHaveAttribute('role')
  expect(name.textContent).toBe('résumé  100%20.py')
  expect(name.querySelector('mark')).not.toBeNull()
  expect(within(card).getByText('Script')).toBeInTheDocument()
  expect(within(card).getByRole('img', { name: 'Script' })).toBeInTheDocument()
  expect(within(card).getByText('PY script · 2 KB')).toBeInTheDocument()
  expect(open).toHaveAttribute('aria-description', 'The script may run')
  expect(screen.queryByText('Authored description')).not.toBeInTheDocument()
  expect(screen.queryByText('metadata-filename')).not.toBeInTheDocument()
  expect(screen.getByText('Match 1 of 1 in the text')).toBeInTheDocument()
  fireEvent.click(name)
  fireEvent.doubleClick(card)
  const context = createEvent.contextMenu(name)
  fireEvent(name, context)
  expect(context.defaultPrevented).toBe(false)
  expect(fetch).not.toHaveBeenCalled()
  expect(defaults.onNavigate).not.toHaveBeenCalled()
  video.currentTime = 42
  rerender(
    body({ query: 'script Open KB resumed', media: [file, { ...savedVideo, position_s: 42 }] }),
  )
  expect(screen.getByText('No matches in the text')).toBeInTheDocument()
  expect(container.querySelector('[data-file-card]')).toBe(card)
  expect(card.querySelector('.file-name')).toBe(name)
  expect(within(card).getByRole('button', { name: 'Open in default app' })).toBe(open)
  expect(container.querySelector('video')).toBe(video)
  expect(container.querySelector('audio')).toBe(audio)
  expect(video.currentTime).toBe(42)
  rerender(body({ query: 'résumé' }))
  expect(name.querySelector('mark')).not.toBeNull()
  fireEvent.click(open)
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe('/api/authors/studio/media/attachment-id/open')
  expect(vi.mocked(fetch).mock.calls[0]?.[1]?.body).toBe('{"reveal":false}')
  expect(name.querySelector('mark')).not.toBeNull()
  rerender(body())
  expect(name.querySelector('mark')).toBeNull()
  expect(name.textContent).toBe('résumé  100%20.py')
  fireEvent.pause(video)
  expect(pause).toHaveBeenCalledOnce()
})

test('keeps unknown, cross-author and cross-origin attachments and inline media outside file actions', () => {
  const { Wrapper } = createFileActionsTestApp(localFileCapabilities)
  const unknown = `<a class="attachment" href="/media/studio/unknown.pdf">Unknown</a><a class="attachment" href="${mediaPath('other', file.path)}">Other author</a><a class="attachment" href="https://other.invalid${mediaPath('studio', file.path)}">Other origin</a><a class="attachment" href="${mediaPath('studio', savedVideo.path)}">Inline video</a>`
  const { container } = render(body({ html: markup() + unknown }), { wrapper: Wrapper })
  expect(container.querySelectorAll('[data-file-card]')).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: 'Open in default app' })).toHaveLength(1)
  for (const label of ['Unknown', 'Other author', 'Other origin', 'Inline video']) {
    expect(screen.getByRole('link', { name: label })).toHaveClass('attachment')
  }
  expect(screen.getByRole('link', { name: 'Other origin' })).toHaveAttribute('target', '_blank')
  expect(container.querySelector('video')?.querySelector('[data-file-action-container]')).toBeNull()
  expect(container.querySelector('audio')?.querySelector('[data-file-action-container]')).toBeNull()
})

test('closes folded actions when a pane is hidden without restoring focus into it', async () => {
  width = 300
  const { Wrapper } = createFileActionsTestApp(localFileCapabilities)
  const { container, rerender } = render(body(), { wrapper: Wrapper })
  const card = container.querySelector('[data-file-card]')!
  const trigger = screen.getByRole('button', { name: 'More for résumé 100%20.py' })
  fireEvent.keyDown(trigger, { key: 'ArrowDown' })
  await waitFor(() => expect(screen.getByRole('menu')).toBeInTheDocument())
  const focus = vi.spyOn(trigger, 'focus')
  rerender(body({}, false))
  await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
  expect(container.querySelector('[data-file-card]')).toBe(card)
  expect(focus).not.toHaveBeenCalled()
  expect(card.querySelector('button')).toBeNull()
  rerender(body())
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  expect(container.querySelector('[data-file-card]')).toBe(card)
})

test('rebuilds file inventory under the same search without replacing native media', () => {
  const { Wrapper } = createFileActionsTestApp(localFileCapabilities)
  const { container, rerender } = render(body({ media: [savedVideo], query: 'résumé' }), {
    wrapper: Wrapper,
  })
  const video = container.querySelector('video')
  expect(container.querySelector('[data-file-card]')).toBeNull()
  expect(screen.getByText('No matches in the text')).toBeInTheDocument()
  rerender(body({ query: 'résumé' }))
  expect(screen.getByText('Match 1 of 1 in the text')).toBeInTheDocument()
  expect(container.querySelector('.file-name mark')).toHaveTextContent('résumé')
  expect(container.querySelector('video')).toBe(video)
  rerender(body({ query: 'résumé', media: [{ ...file, size: 4000 }, savedVideo] }))
  expect(screen.getByText('PY script · 4 KB')).toBeInTheDocument()
  expect(container.querySelector('.file-name mark')).toHaveTextContent('résumé')
  expect(container.querySelector('video')).toBe(video)
})

test('removes stale portals and menus across HTML, author, post and unmount changes', async () => {
  width = 300
  const { Wrapper } = createFileActionsTestApp(localFileCapabilities)
  const { container, rerender, unmount } = render(body({ query: 'résumé' }), { wrapper: Wrapper })
  const firstCard = container.querySelector('[data-file-card]')!
  const trigger = screen.getByRole('button', { name: 'More for résumé 100%20.py' })
  fireEvent.keyDown(trigger, { key: 'ArrowDown' })
  await waitFor(() => expect(screen.getByRole('menu')).toBeInTheDocument())
  const focus = vi.spyOn(trigger, 'focus')
  rerender(body({ html: markup() + '<p>New body</p>', query: 'résumé' }))
  await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
  expect(firstCard.isConnected).toBe(false)
  expect(firstCard.querySelector('[data-page-slot="actions"]')?.childNodes).toHaveLength(0)
  expect(container.querySelectorAll('[data-file-card]')).toHaveLength(1)
  expect(container.querySelector('.file-name mark')).toHaveTextContent('résumé')
  expect(focus).not.toHaveBeenCalled()
  rerender(body({ author: 'different', query: 'résumé' }))
  expect(container.querySelector('[data-file-card]')).toBeNull()
  expect(screen.getByRole('link', { name: 'Authored descriptionSaved facts' })).toBeInTheDocument()
  rerender(body({ postId: 'different-post' }))
  expect(container.querySelector('[data-file-card]')).toBeNull()
  rerender(body())
  const lastCard = container.querySelector('[data-file-card]')!
  expect(lastCard).toBeInTheDocument()
  unmount()
  expect(lastCard.isConnected).toBe(false)
  expect(lastCard.querySelector('[data-page-slot="actions"]')?.childNodes).toHaveLength(0)
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})

test('keeps a persistent error accessible inside the image viewer with no per-image file actions', async () => {
  const { Wrapper, controller } = createFileActionsTestApp(localFileCapabilities)
  render(body(), { wrapper: Wrapper })
  act(() => controller.showNotice({ kind: 'error', message: 'The file is missing.' }))
  expect(screen.getByRole('alert')).toHaveTextContent('The file is missing.')
  fireEvent.click(screen.getByRole('button', { name: 'Open image: Drawing' }))
  const dialog = screen.getByRole('dialog', { name: 'Post image viewer' })
  expect(within(dialog).getByRole('alert')).toHaveTextContent('The file is missing.')
  expect(within(dialog).queryByRole('button', { name: 'Open in default app' })).toBeNull()
  expect(within(dialog).queryByRole('link', { name: 'Download a copy' })).toBeNull()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close image viewer' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(screen.getByRole('alert')).toHaveTextContent('The file is missing.')
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss file notice' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('decorates retained files once under StrictMode and uses remote-safe actions', () => {
  const { Wrapper } = createFileActionsTestApp()
  const retained = {
    ...file,
    file_type: 'pdf' as const,
    path: 'first-post/notes.pdf',
    removed: true,
  }
  const { container } = render(
    <StrictMode>
      {body({
        html: `<section class="removed-media">${markup(retained)}</section>`,
        media: [retained],
      })}
    </StrictMode>,
    { wrapper: Wrapper },
  )
  expect(container.querySelectorAll('[data-file-card]')).toHaveLength(1)
  expect(screen.queryByRole('button', { name: 'Open in default app' })).toBeNull()
  expect(screen.getByRole('link', { name: 'View in a new tab' })).toHaveAttribute(
    'href',
    mediaPath('studio', retained.path),
  )
  expect(screen.getByRole('link', { name: 'Download a copy' })).toHaveAttribute(
    'download',
    'notes.pdf',
  )
})
