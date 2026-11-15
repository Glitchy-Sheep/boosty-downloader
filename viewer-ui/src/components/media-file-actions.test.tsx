import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState, type ReactNode } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { AudioList } from '@/components/audio-list'
import { MediaTile } from '@/components/media-tile'
import { MediaViewer } from '@/components/media-viewer'
import { PostHeader } from '@/components/post-header'
import type { MediaItem, MediaPage, OpenerCapabilities } from '@/lib/api.gen'
import { createPlayerStore, PlayerProvider, type PlayerStore } from '@/lib/player'
import { createFileActionsTestApp, localFileCapabilities } from '@/test/file-actions'
import { savedPost, savedVideo } from '@/test/post-fixtures'

vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    params,
  }: {
    children: ReactNode
    params: { author: string; postId: string }
  }) => <a href={`/a/${params.author}/p/${params.postId}`}>{children}</a>,
}))

const author = 'автор %'
const authorSegment = encodeURIComponent(author)

function mediaPage(item: MediaItem): MediaPage {
  return {
    items: [item],
    posts: { [item.post_id]: savedPost },
    counts: { all: 1, images: 0, videos: 0, audio: 0, files: 0 },
    missing: 0,
  }
}

function recordOpener() {
  const request = vi.fn(async (url: string, init?: RequestInit) => {
    if (!url.endsWith('/open') || init?.method !== 'POST')
      throw new Error(`Unexpected request: ${url}`)
    return new Response(null, { status: 204 })
  })
  vi.stubGlobal('fetch', request)
  return request
}

async function selectAction(label: string) {
  const item = await screen.findByRole('menuitem', { name: label })
  act(() => item.focus())
  fireEvent.keyDown(item, { key: 'Enter' })
  await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
}

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(400)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
    new DOMRect(0, 0, 800, 400),
  )
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test.each([false, true])(
  'fullscreen file actions pause only Open, including removed=%s',
  async (removed) => {
    const request = recordOpener()
    const item = { ...savedVideo, id: 'opaque /%', path: 'first-post/raw %2F.mp4', removed }
    const { Wrapper } = createFileActionsTestApp(localFileCapabilities)
    const copy = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText: copy } })
    render(
      <MediaViewer
        author={author}
        data={mediaPage(item)}
        openId={item.id}
        active
        onShow={vi.fn()}
        onClose={vi.fn()}
        onRestoreFocus={vi.fn(async () => true)}
        postHref={() => '#post'}
        onPost={vi.fn()}
      />,
      { wrapper: Wrapper },
    )
    const dialog = screen.getByRole('dialog', { name: 'Media viewer' })
    const video = dialog.querySelector('video')!
    video.currentTime = 42
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
    const play = vi.spyOn(video, 'play').mockResolvedValue()
    const initialPlayCalls = play.mock.calls.length
    const reveal = within(dialog).getByRole('button', { name: 'Show in Finder' })
    fireEvent.click(reveal)
    await waitFor(() => expect(reveal).toBeEnabled())
    expect(request).toHaveBeenLastCalledWith(
      `/api/authors/${authorSegment}/media/opaque%20%2F%25/open`,
      expect.objectContaining({ method: 'POST', body: '{"reveal":true}' }),
    )
    expect(pause).not.toHaveBeenCalled()

    fireEvent.keyDown(within(dialog).getByRole('button', { name: 'More for raw %2F.mp4' }), {
      key: 'Enter',
    })
    await selectAction('Copy path')
    expect(copy).toHaveBeenCalledExactlyOnceWith(`/Library/${author}/first-post/raw %2F.mp4`)
    expect(within(dialog).getByRole('status')).toHaveTextContent('Path copied')
    expect(pause).not.toHaveBeenCalled()

    fireEvent.keyDown(within(dialog).getByRole('button', { name: 'More for raw %2F.mp4' }), {
      key: 'Enter',
    })
    const download = await screen.findByRole('menuitem', { name: 'Download a copy' })
    expect(download).toHaveAttribute('download', 'raw %2F.mp4')
    expect(download).toHaveAttribute('href', `/media/${authorSegment}/first-post/raw%20%252F.mp4`)
    // Browser download acceptance covers navigation; jsdom only observes player side effects.
    download.addEventListener('click', (event) => event.preventDefault(), { once: true })
    fireEvent.click(download)
    fireEvent.keyDown(download, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
    expect(pause).not.toHaveBeenCalled()
    expect(request).toHaveBeenCalledTimes(1)

    fireEvent.click(within(dialog).getByRole('button', { name: 'Open in default app' }))
    expect(pause).toHaveBeenCalledOnce()
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: 'Open in default app' })).toBeEnabled(),
    )
    expect(request).toHaveBeenLastCalledWith(
      `/api/authors/${authorSegment}/media/opaque%20%2F%25/open`,
      expect.objectContaining({ method: 'POST', body: '{"reveal":false}' }),
    )
    expect(dialog.querySelector('video')).toBe(video)
    expect(video.currentTime).toBe(42)
    expect(play).toHaveBeenCalledTimes(initialPlayCalls)
  },
)

function AudioSurface({
  item,
  store,
  surface,
}: {
  item: MediaItem
  store: PlayerStore
  surface: 'list' | 'grid'
}) {
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null)
  return (
    <PlayerProvider store={store}>
      <div ref={setScroller}>
        {surface === 'list' ? (
          <AudioList
            author={author}
            page={mediaPage(item)}
            active
            scroller={scroller}
            listKey="all"
          />
        ) : (
          <MediaTile
            author={author}
            item={item}
            post={savedPost}
            active
            onOpen={vi.fn()}
            favorite={null}
          />
        )}
      </div>
    </PlayerProvider>
  )
}

test.each([
  { surface: 'list' as const, removed: false },
  { surface: 'list' as const, removed: true },
  { surface: 'grid' as const, removed: false },
  { surface: 'grid' as const, removed: true },
])(
  '$surface audio Open pauses its shared player without replacing the queue, removed=$removed',
  async ({ surface, removed }) => {
    const item: MediaItem = {
      ...savedVideo,
      kind: 'audio',
      file_type: 'audio',
      path: 'first-post/song.mp3',
      removed,
    }
    const store = createPlayerStore()
    store.start(author, mediaPage(item), item.id)
    store.setPlaying(true)
    const original = store.getSnapshot()!
    const audio = document.createElement('audio')
    audio.currentTime = 63
    const pause = vi.spyOn(audio, 'pause').mockImplementation(() => store.setPlaying(false))
    const play = vi.spyOn(audio, 'play').mockResolvedValue()
    store.attach(audio)
    const request = recordOpener()
    const { Wrapper } = createFileActionsTestApp(localFileCapabilities)
    render(<AudioSurface item={item} store={store} surface={surface} />, { wrapper: Wrapper })

    const openMenu = async () => {
      if (surface === 'list')
        fireEvent.keyDown(await screen.findByRole('button', { name: 'More for song.mp3' }), {
          key: 'Enter',
        })
      else fireEvent.contextMenu(await screen.findByRole('button', { name: /^Play Saved video/ }))
    }
    await openMenu()
    await selectAction('Show in Finder')
    expect(request).toHaveBeenLastCalledWith(
      `/api/authors/${authorSegment}/media/opaque-video/open`,
      expect.objectContaining({ body: '{"reveal":true}' }),
    )
    expect(pause).not.toHaveBeenCalled()
    expect(store.getSnapshot()).toBe(original)

    await openMenu()
    await selectAction('Open in default app')
    expect(pause).toHaveBeenCalledOnce()
    expect(request).toHaveBeenLastCalledWith(
      `/api/authors/${authorSegment}/media/opaque-video/open`,
      expect.objectContaining({ body: '{"reveal":false}' }),
    )
    expect(store.getSnapshot()).toEqual({ ...original, playing: false })
    expect(store.getSnapshot()?.queue).toBe(original.queue)
    expect(audio.currentTime).toBe(63)
    expect(play).not.toHaveBeenCalled()
    store.attach(null)
  },
)

test.each([
  { hasFolder: true, open: true, folders: true, visible: true },
  { hasFolder: false, open: true, folders: true, visible: false },
  { hasFolder: true, open: false, folders: true, visible: false },
  { hasFolder: true, open: true, folders: false, visible: false },
])(
  'post folder availability: hasFolder=$hasFolder open=$open folders=$folders',
  async ({ hasFolder, open, folders, visible }) => {
    const capabilities: OpenerCapabilities = { ...localFileCapabilities, open, folders }
    const { Wrapper } = createFileActionsTestApp(capabilities)
    const request = recordOpener()
    render(
      <PostHeader
        author={author}
        post={{ ...savedPost, id: 'post /%', has_folder: hasFolder }}
        favoritePending={false}
        favoriteError={null}
        onFavorite={vi.fn()}
        seenPending={false}
        seenError={null}
        onSeen={vi.fn()}
        onTag={vi.fn()}
      />,
      { wrapper: Wrapper },
    )
    const folder = screen.queryByRole('button', { name: 'Open the post folder in Finder' })
    if (!visible) {
      expect(folder).not.toBeInTheDocument()
      expect(request).not.toHaveBeenCalled()
      return
    }
    expect(folder).toBeVisible()
    fireEvent.click(folder!)
    await waitFor(() => expect(folder).toBeEnabled())
    expect(request).toHaveBeenCalledExactlyOnceWith(
      `/api/authors/${authorSegment}/posts/post%20%2F%25/open`,
      expect.objectContaining({ method: 'POST', body: '{}' }),
    )
  },
)
