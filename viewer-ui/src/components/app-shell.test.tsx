import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'

import { AppShell } from '@/components/app-shell'

test('names the library and its current page without claiming any library data', async () => {
  const router = createRouter({
    routeTree: createRootRoute({ component: AppShell }),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(<RouterProvider router={router} />)

  expect(await screen.findByRole('link', { name: 'Boosty Library' })).toHaveAttribute('href', '/')
  const navigation = screen.getByRole('navigation', { name: 'Library' })
  expect(
    within(navigation).getByRole('link', { name: 'Authors', current: 'page' }),
  ).toHaveAttribute('href', '/')
  expect(screen.getByRole('main', { name: 'Authors' })).toBeEmptyDOMElement()
})
