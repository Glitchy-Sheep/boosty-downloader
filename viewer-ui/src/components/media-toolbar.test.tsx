import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { MediaToolbar, type MediaFilterUpdate } from '@/components/media-toolbar'
import type { MediaSearch } from '@/lib/media-filters'

const counts = { all: 2030, images: 2000, videos: 20, audio: 10, files: 12 }

test('shows every canonical count and changes views without inventing filter values', () => {
  const change = vi.fn()
  render(<MediaToolbar filters={{}} counts={counts} updating={false} onChange={change} />)
  expect(screen.getByRole('button', { name: 'All 2,030' })).toHaveAttribute('aria-pressed', 'true')
  const views = [
    { name: 'Photos 2,000', view: 'images' },
    { name: 'Videos 20', view: 'videos' },
    { name: 'Audio 10', view: 'audio' },
    { name: 'Files 12', view: 'files' },
    { name: 'All 2,030', view: undefined },
  ]
  for (const view of views) {
    fireEvent.click(screen.getByRole('button', { name: view.name }))
    expect(change).toHaveBeenLastCalledWith({ view: view.view })
  }
})

test('toggles combined filters and exposes refresh state without replacing known counts', () => {
  const change = vi.fn<(update: MediaFilterUpdate) => void>()
  const patch = (previous: MediaSearch = {}) => {
    const update = change.mock.lastCall![0]
    return typeof update === 'function' ? update(previous) : update
  }
  const { rerender } = render(
    <MediaToolbar filters={{ view: 'videos' }} counts={undefined} updating onChange={change} />,
  )
  expect(screen.getByRole('button', { name: 'Videos …' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('status', { name: 'Updating media' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Unseen' }))
  expect(patch()).toEqual({ unseen: 1 })
  fireEvent.click(screen.getByRole('button', { name: 'Favorites only' }))
  expect(patch()).toEqual({ fav: 1 })
  fireEvent.click(screen.getByRole('button', { name: 'Oldest first' }))
  expect(patch()).toEqual({ order: 'oldest' })
  rerender(
    <MediaToolbar
      filters={{ unseen: 1, fav: 1, order: 'oldest' }}
      counts={counts}
      updating={false}
      onChange={change}
    />,
  )
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  for (const name of ['Unseen', 'Favorites only', 'Oldest first'])
    expect(screen.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Unseen' }))
  expect(patch({ unseen: 1 })).toEqual({ unseen: undefined })
  fireEvent.click(screen.getByRole('button', { name: 'Favorites only' }))
  expect(patch({ fav: 1 })).toEqual({ fav: undefined })
  fireEvent.click(screen.getByRole('button', { name: 'Oldest first' }))
  expect(patch({ order: 'oldest' })).toEqual({ order: undefined })
})
