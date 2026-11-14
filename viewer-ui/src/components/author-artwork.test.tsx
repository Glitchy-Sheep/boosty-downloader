import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { AuthorArtwork } from '@/components/author-artwork'

test('keeps a placeholder when no artwork exists', () => {
  const { container } = render(<AuthorArtwork src={null} className="size-full" fallback={<span>WN</span>} />)

  expect(screen.getByText('WN')).toBeVisible()
  expect(container.querySelector('img')).toBeNull()
})

test('replaces a loading placeholder with decorative artwork after success', () => {
  const { container } = render(<AuthorArtwork src="/avatar.png" className="size-full" fallback={<span>WN</span>} />)
  const image = container.querySelector('img')!
  expect(screen.getByText('WN')).toBeInTheDocument()

  fireEvent.load(image)

  expect(screen.queryByText('WN')).not.toBeInTheDocument()
  expect(image).toHaveAttribute('alt', '')
  expect(image).not.toHaveClass('invisible')
})

test('retains a failed placeholder and retries when the artwork URL changes', () => {
  const props = { className: 'size-full', fallback: <span>WN</span> }
  const { container, rerender } = render(<AuthorArtwork src="/old.png" {...props} />)
  fireEvent.error(container.querySelector('img')!)
  expect(screen.getByText('WN')).toBeVisible()
  expect(container.querySelector('img')).toBeNull()

  rerender(<AuthorArtwork src="/old.png" {...props} />)
  expect(container.querySelector('img')).toBeNull()
  rerender(<AuthorArtwork src="/new.png" {...props} />)
  const image = container.querySelector('img')!
  expect(image).toHaveAttribute('src', '/new.png')
  fireEvent.load(image)
  expect(screen.queryByText('WN')).not.toBeInTheDocument()

  rerender(<AuthorArtwork src={null} {...props} />)
  expect(screen.getByText('WN')).toBeVisible()
  expect(container.querySelector('img')).toBeNull()
})
