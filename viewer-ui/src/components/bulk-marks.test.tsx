import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { BulkMarks } from '@/components/bulk-marks'
import type { PostList } from '@/lib/api.gen'
import { TabActive } from '@/lib/author-tab'
import { toPostFilters, type Filters } from '@/lib/filters'
import { createQueryClient } from '@/lib/queries'
import { savedRow } from '@/test/post-fixtures'

afterEach(() => vi.unstubAllGlobals())

const listing: PostList = {
  rows: [
    { ...savedRow, id: 'unseen', seen: false, updated: false },
    { ...savedRow, id: 'seen', seen: true, updated: false },
    { ...savedRow, id: 'updated', seen: true, updated: true },
    { ...savedRow, id: 'locked', access: 'locked', seen: false, updated: false },
  ],
  months: [{ month: '2026-01', count: 4 }],
  total: 4,
}

function pendingResponse() {
  let resolve!: (response: Response) => void
  const response = new Promise<Response>((done) => {
    resolve = done
  })
  return { response, resolve }
}

function setup(filters: Filters = { tag: 'stream' }) {
  const client = createQueryClient()
  const props = { author: 'studio', filters, posts: listing, disabled: false }
  const element = (next = props, active = true) => (
    <QueryClientProvider client={client}>
      <TabActive value={active}>
        <BulkMarks {...next} />
      </TabActive>
    </QueryClientProvider>
  )
  const rendered = render(element())
  return { client, props, element, ...rendered }
}

async function choose(seen = true) {
  fireEvent.keyDown(screen.getByRole('button', { name: 'Mark posts' }), { key: 'Enter' })
  fireEvent.click(
    await screen.findByRole('menuitem', { name: seen ? 'Mark all as seen' : 'Mark all as unseen' }),
  )
  return screen.findByRole('dialog')
}

test.each([true, false])(
  'confirms actual changes for seen=%s and cancel performs no write',
  async (seen) => {
    const request = vi.fn()
    vi.stubGlobal('fetch', request)
    const { client, unmount } = setup()
    const dialog = await choose(seen)
    expect(within(dialog).getByRole('heading')).toHaveTextContent(
      `Mark 2 posts as ${seen ? 'seen' : 'unseen'}?`,
    )
    expect(within(dialog).getByRole('list', { name: 'Selected filters' })).toHaveTextContent(
      '#stream',
    )
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mark posts' })).toHaveFocus())
    expect(request).not.toHaveBeenCalled()
    unmount()
    client.clear()
  },
)

test('preserves the confirmed filters, reports processed separately, and accepts the POST change count', async () => {
  const pending = pendingResponse()
  const request = vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return pending.response
    return Response.json({ active: true, total: 3, completed: 2, changed: 1 })
  })
  vi.stubGlobal('fetch', request)
  const { client, props, element, rerender, unmount } = setup()
  await choose()
  rerender(
    element({ ...props, filters: { q: 'new search' }, posts: { rows: [], months: [], total: 0 } }),
  )
  expect(screen.getByRole('dialog')).toHaveTextContent('#stream')
  fireEvent.click(screen.getByRole('button', { name: 'Mark as seen' }))
  const progress = await screen.findByRole('progressbar', { name: 'Marking progress' })
  expect(progress).toHaveAttribute('value', '2')
  expect(progress).toHaveAttribute('max', '3')
  expect(screen.getByText('2 of 3 posts processed')).toBeVisible()
  expect(screen.getByText('1 post changed')).toBeVisible()
  expect(
    request.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === 'POST',
    )?.[1],
  ).toMatchObject({
    body: JSON.stringify({ filters: toPostFilters({ tag: 'stream' }), seen: true }),
  })
  pending.resolve(Response.json({ count: 1 }))
  expect(await screen.findByText('Marked 1 post as seen.')).toBeVisible()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  unmount()
  client.clear()
})

test('closing progress keeps the write pending and offers the same operation when reopened', async () => {
  const pending = pendingResponse()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return pending.response
      return Response.json({ active: true, total: 3, completed: 1, changed: 1 })
    }),
  )
  const { client, unmount } = setup()
  await choose()
  fireEvent.click(screen.getByRole('button', { name: 'Mark as seen' }))
  await screen.findByRole('progressbar')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  const show = screen.getByRole('button', { name: 'Show marking progress' })
  expect(show).toHaveTextContent('1 / 3')
  fireEvent.click(show)
  expect(screen.getByRole('dialog')).toHaveTextContent('1 of 3 posts processed')
  pending.resolve(Response.json({ count: 2 }))
  expect(await screen.findByText('Marked 2 posts as seen.')).toBeVisible()
  unmount()
  client.clear()
})

test('an inactive or unavailable progress response never claims completion', async () => {
  const pending = pendingResponse()
  const request = vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return pending.response
    return Response.json({ active: false, total: null, completed: 0, changed: 0 })
  })
  vi.stubGlobal('fetch', request)
  const { client, unmount } = setup()
  await choose()
  fireEvent.click(screen.getByRole('button', { name: 'Mark as seen' }))
  expect(await screen.findByText('Waiting for the marking result...')).toBeVisible()
  expect(screen.queryByText(/^Marked /)).not.toBeInTheDocument()
  pending.resolve(
    Response.json(
      { error: { code: 'busy', message: 'Another marking operation is running.' } },
      { status: 409 },
    ),
  )
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Another marking operation is running.',
  )
  expect(screen.queryByText(/^Marked /)).not.toBeInTheDocument()
  unmount()
  client.clear()
})

test('failure retry permits a zero-change repair and retains the original scope', async () => {
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method !== 'POST')
        return Response.json({ active: false, total: null, completed: 0, changed: 0 })
      writes += 1
      if (writes === 1)
        return Response.json(
          { error: { code: 'write_failed', message: 'Index failed.' } },
          { status: 409 },
        )
      return Response.json({ count: 0 })
    }),
  )
  const { client, props, element, rerender, unmount } = setup()
  await choose()
  fireEvent.click(screen.getByRole('button', { name: 'Mark as seen' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Index failed.')
  const saved = {
    ...listing,
    rows: listing.rows.map((row) => ({ ...row, seen: true, updated: false })),
  }
  rerender(element({ ...props, posts: saved }))
  fireEvent.click(screen.getByRole('button', { name: 'Retry marking' }))
  expect(screen.getByRole('heading')).toHaveTextContent('Mark 0 posts as seen?')
  expect(screen.getByRole('button', { name: 'Mark as seen' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Mark as seen' }))
  expect(await screen.findByText('Marked 0 posts as seen.')).toBeVisible()
  expect(writes).toBe(2)
  unmount()
  client.clear()
})

test('retry never invents a remaining count from another or unavailable filtered list', async () => {
  const request = vi
    .fn()
    .mockResolvedValue(
      Response.json({ error: { code: 'failed', message: 'Write failed.' } }, { status: 503 }),
    )
  vi.stubGlobal('fetch', request)
  const { client, props, element, rerender, unmount } = setup({
    q: 'original',
    tag: 'stream',
    kind: 'videos',
    unseen: 1,
    fav: 1,
    incomplete: 1,
    locked: 1,
  })
  await choose()
  fireEvent.click(screen.getByRole('button', { name: 'Mark as seen' }))
  await screen.findByRole('alert')
  rerender(element({ ...props, filters: { tag: 'other' }, disabled: true }))
  fireEvent.click(screen.getByRole('button', { name: 'Retry marking' }))
  expect(screen.getByRole('heading')).toHaveTextContent('Retry marking posts as seen?')
  expect(screen.getByText(/remaining count is unavailable/)).toHaveTextContent(
    'originally confirmed 2 posts',
  )
  expect(screen.getByRole('list')).toHaveTextContent('#stream')
  expect(screen.getByRole('list')).not.toHaveTextContent('#other')
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(
    request.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST'),
  ).toHaveLength(1)
  unmount()
  client.clear()
})

test('unavailable and empty lists cannot open new bulk actions', async () => {
  const { client, props, element, rerender, unmount } = setup({})
  rerender(element({ ...props, disabled: true }))
  expect(screen.getByRole('button', { name: 'Mark posts' })).toBeDisabled()
  rerender(element({ ...props, posts: { rows: [], months: [], total: 0 } }))
  expect(screen.getByRole('button', { name: 'Mark posts' })).toBeDisabled()
  await act(async () => {})
  unmount()
  client.clear()
})

test('unknown totals stay indeterminate and a progress read failure does not stop saving', async () => {
  const pending = pendingResponse()
  let progressAvailable = false
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return pending.response
      if (!progressAvailable)
        return Response.json(
          { error: { code: 'read_failed', message: 'Read failed.' } },
          { status: 503 },
        )
      return Response.json({ active: true, total: null, completed: 0, changed: 0 })
    }),
  )
  const { client, unmount } = setup({})
  await choose()
  expect(screen.getByRole('list')).toHaveTextContent('All posts')
  fireEvent.click(screen.getByRole('button', { name: 'Mark as seen' }))
  expect(await screen.findByText('Progress is unavailable. Marking continues.')).toBeVisible()
  progressAvailable = true
  await act(() => client.invalidateQueries({ queryKey: ['bulk-mark-progress'] }))
  const progress = await screen.findByRole('progressbar')
  expect(progress).not.toHaveAttribute('value')
  expect(screen.getByText('0 posts processed')).toBeVisible()
  expect(screen.queryByText(/^Marked /)).not.toBeInTheDocument()
  pending.resolve(Response.json({ count: 2 }))
  expect(await screen.findByText('Marked 2 posts as seen.')).toBeVisible()
  unmount()
  client.clear()
})

test('leaving Posts dismisses its confirmation without writing or restoring hidden focus', async () => {
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  const { client, props, element, rerender, unmount } = setup()
  const trigger = screen.getByRole('button', { name: 'Mark posts' })
  await choose()
  const focus = vi.spyOn(trigger, 'focus')
  rerender(element(props, false))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(focus).not.toHaveBeenCalled()
  expect(request).not.toHaveBeenCalled()
  rerender(element())
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  unmount()
  client.clear()
})

test('a hidden bulk operation keeps running and its unseen result can be reopened with its original filters', async () => {
  const pending = pendingResponse()
  const request = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === 'POST'
      ? pending.response
      : Response.json({ active: true, total: 3, completed: 1, changed: 1 }),
  )
  vi.stubGlobal('fetch', request)
  const { client, props, element, rerender, unmount } = setup()
  await choose(false)
  fireEvent.click(screen.getByRole('button', { name: 'Mark as unseen' }))
  await screen.findByRole('progressbar')
  rerender(element(props, false))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(client.isMutating()).toBe(1)
  rerender(element({ ...props, filters: { tag: 'another' } }))
  fireEvent.click(screen.getByRole('button', { name: 'Show marking progress' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('#stream')
  pending.resolve(Response.json({ count: 2 }))
  expect(await screen.findByText('Marked 2 posts as unseen.')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  fireEvent.keyDown(screen.getByRole('button', { name: 'Mark posts' }), { key: 'Enter' })
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Last marking result' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('Marked 2 posts as unseen.')
  expect(screen.getByRole('dialog')).toHaveTextContent('#stream')
  expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  unmount()
  client.clear()
})
