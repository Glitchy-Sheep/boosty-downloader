import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { AuthorsPage } from '@/components/authors-page'
import type { Author } from '@/lib/api.gen'

function author(overrides: Partial<Author> = {}): Author {
  return {
    name: 'writer', title: 'Writer Notes', description: 'Sketches and stories',
    avatar_url: null, cover_url: null, posts: 12, locked: 2, unseen: 4, favorites: 1,
    storage: { videos: 3_000_000, images: 1_000_000, audio: 0, files: 0 },
    ...overrides,
  }
}

test('orders cards by display title and name without changing the response', () => {
  const authors = [
    author({ name: 'zebra', title: 'Amber', posts: 2 }),
    author({ name: 'zero', title: 'Zero', posts: 3 }),
    author({ name: 'alpha', title: 'Amber', posts: 5 }),
  ]
  render(<AuthorsPage authors={authors} />)

  expect(screen.getAllByRole('link').map((link) => link.getAttribute('href')))
    .toEqual(['/a/alpha', '/a/zebra', '/a/zero'])
  expect(authors.map((item) => item.name)).toEqual(['zebra', 'zero', 'alpha'])
  expect(screen.getByText('3 authors · 10 posts · 12 unseen')).toBeInTheDocument()
})

test('names a card by title and describes storage kinds and unseen posts in sentences', () => {
  render(<AuthorsPage authors={[author()]} />)
  const card = screen.getByRole('link', { name: 'Writer Notes' })

  expect(card).toHaveAccessibleDescription('4 MB of media on disk: videos 3 MB, photos 1 MB. 4 unseen.')
  expect(within(card).getByText('12 posts')).toBeInTheDocument()
  expect(within(card).getByText('2 locked')).toBeInTheDocument()
  expect(within(card).getByText('4 unseen')).toBeInTheDocument()
  expect(within(card).getAllByRole('listitem').map((item) => item.textContent))
    .toEqual(['Videos3 MB', 'Photos1 MB'])
  expect(screen.queryByRole('region', { name: 'Disk space' })).not.toBeInTheDocument()
  expect(within(card).getByText('of media on disk')).toBeVisible()
})

test('uses the name when the title is empty and encodes the card address once', () => {
  render(<AuthorsPage authors={[author({ name: 'writer%20name', title: '', unseen: 0 })]} />)
  const card = screen.getByRole('link', { name: 'writer%20name' })

  expect(card).toHaveAttribute('href', '/a/writer%2520name')
  expect(card).toHaveAccessibleDescription('4 MB of media on disk: videos 3 MB, photos 1 MB.')
  expect(within(card).queryByText('0 unseen')).not.toBeInTheDocument()
  expect(within(card).getByText('W')).toBeInTheDocument()
})

test('shows one combined library total only when multiple authors have media', () => {
  render(<AuthorsPage authors={[
    author(),
    author({ name: 'artist', title: 'Art', storage: { videos: 0, images: 2_000_000, audio: 1_000_000, files: 0 } }),
  ]} />)
  const library = screen.getByRole('region', { name: 'Disk space' })

  expect(within(library).getByText('7 MB')).toBeInTheDocument()
  expect(within(library).getAllByRole('listitem').map((item) => item.textContent))
    .toEqual(['Videos3 MB', 'Photos3 MB', 'Audio1 MB'])
})

test('names a single storage kind without repeating it in a legend', () => {
  render(<AuthorsPage authors={[author({ storage: { videos: 0, images: 3_000_000, audio: 0, files: 0 } })]} />)
  const card = screen.getByRole('link', { name: 'Writer Notes' })

  expect(card).toHaveAccessibleDescription('3 MB of photos on disk. 4 unseen.')
  expect(within(card).queryByRole('list')).not.toBeInTheDocument()
  expect(within(card).getByText('of photos', { exact: false, selector: 'p' })).toBeVisible()
  expect(within(card).getByText('on disk')).toBeVisible()
})

test('keeps empty storage explicit without bars or a library total', () => {
  const empty = { videos: 0, images: 0, audio: 0, files: 0 }
  const { container } = render(<AuthorsPage authors={[
    author({ storage: empty, unseen: 0 }),
    author({ name: 'other', title: 'Other', storage: empty, unseen: 0 }),
  ]} />)

  for (const card of screen.getAllByRole('link')) {
    expect(card).toHaveAccessibleDescription('No media on disk.')
    expect(within(card).getByText('No media on disk', { selector: 'p' })).toBeVisible()
  }
  expect(container.querySelector('[data-storage-bar]')).toBeNull()
  expect(screen.queryByRole('region', { name: 'Disk space' })).not.toBeInTheDocument()
})

test('shows an empty library without inventing authors', () => {
  render(<AuthorsPage authors={[]} />)

  expect(screen.getByRole('heading', { name: 'Authors', level: 1 })).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('No authors yet. Download posts to this library to see them here.')
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Disk space' })).not.toBeInTheDocument()
})

test('treats author text as text and falls back when artwork cannot load', () => {
  const { container } = render(<AuthorsPage authors={[
    author({ title: '<b>Artist</b>', description: '<img src=x onerror=alert(1)>', avatar_url: '/bad-avatar.png', cover_url: '/bad-cover.png' }),
  ]} />)
  const card = screen.getByRole('link', { name: '<b>Artist</b>' })

  expect(within(card).getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
  expect(container.querySelector('b')).toBeNull()
  expect(container.querySelectorAll('img')).toHaveLength(2)
  for (const image of container.querySelectorAll('img')) fireEvent.error(image)
  expect(container.querySelector('img')).toBeNull()
  expect(card).toHaveAccessibleName('<b>Artist</b>')
})
