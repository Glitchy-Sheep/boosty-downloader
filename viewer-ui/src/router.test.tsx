import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { createQueryClient } from '@/lib/queries'
import { createViewerRouter } from '@/router'

beforeEach(() => vi.spyOn(window, 'scrollTo').mockImplementation(() => {}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function renderViewer(address = '/') {
  const queryClient = createQueryClient()
  const router = createViewerRouter(queryClient, createMemoryHistory({ initialEntries: [address] }))
  const view = render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>)
  return { ...view, queryClient, router }
}

test('shows progress while authors load and then the real empty state', async () => {
  let finish: (value: Response) => void = () => { throw new Error('Request has not started') }
  const pending = new Promise<Response>(resolve => { finish = resolve })
  vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending))
  const { queryClient } = renderViewer()

  expect(await screen.findByRole('status')).toHaveTextContent('Loading authors')
  finish(Response.json([]))
  expect(await screen.findByRole('heading', { name: 'Authors' })).toBeVisible()
  expect(screen.getByRole('status')).toHaveTextContent('No authors yet.')
  queryClient.clear()
})

test('retry reloads a failed query and replaces the error with library data', async () => {
  const request = vi.fn()
    .mockResolvedValueOnce(Response.json({ error: { code: 'library_unavailable', message: 'The library is unavailable.' } }, { status: 409 }))
    .mockResolvedValueOnce(Response.json([]))
  vi.stubGlobal('fetch', request)
  const { queryClient } = renderViewer()

  expect(await screen.findByRole('alert')).toHaveTextContent('The library is unavailable.')
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('heading', { name: 'Authors' })).toBeVisible()
  expect(request).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  queryClient.clear()
})

test('unknown local routes have a route back to the library and no authors request', async () => {
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  const { queryClient } = renderViewer('/not-a-library-route')

  expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Back to authors' })).toHaveAttribute('href', '/')
  expect(request).not.toHaveBeenCalled()
  queryClient.clear()
})
