import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { AppShell } from '@/components/app-shell'

test('names the library and its current page without claiming any library data', () => {
  render(<AppShell />)

  expect(screen.getByRole('link', { name: 'Boosty Library' })).toHaveAttribute('href', '/')
  const navigation = screen.getByRole('navigation', { name: 'Library' })
  expect(within(navigation).getByRole('link', { name: 'Authors', current: 'page' }))
    .toHaveAttribute('href', '/')
  expect(screen.getByRole('main', { name: 'Authors' })).toBeEmptyDOMElement()
})
