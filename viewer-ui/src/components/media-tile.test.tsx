import { fireEvent, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { FavoriteButton } from '@/components/favorite-button'
import { MediaTile } from '@/components/media-tile'
import { MediaSection } from '@/components/removed-media'
import { renderWithMediaActions as render } from '@/test/file-actions'
import { savedPost, savedVideo } from '@/test/post-fixtures'

test('opens a video and keeps its favorite action separate while showing resume state', () => {
  const open = vi.fn()
  const favorite = vi.fn()
  render(
    <MediaTile
      author="studio"
      item={savedVideo}
      post={savedPost}
      active
      onOpen={open}
      favorite={<FavoriteButton favorite pending={false} onToggle={favorite} />}
    />,
  )
  const button = screen.getByRole('button', { name: 'Open Saved post' })
  expect(button.querySelector('[data-art] img')).toBeNull()
  expect(screen.getByText('1:40')).toBeVisible()
  expect(screen.getByTitle('20% played').firstElementChild).toHaveStyle({ width: '20%' })
  fireEvent.click(button)
  expect(open).toHaveBeenCalledWith(savedVideo.id)
  fireEvent.click(screen.getByRole('button', { name: 'Remove from favorites' }))
  expect(favorite).toHaveBeenCalledOnce()
  expect(open).toHaveBeenCalledOnce()
  expect(button.querySelector('button')).toBeNull()
})

test('uses thumbnails, labels retained media and keeps inactive tiles quiet', () => {
  const open = vi.fn()
  const item = {
    ...savedVideo,
    kind: 'images' as const,
    thumb_path: 'folder/thumb #1.png',
    removed: true,
    finished: true,
  }
  const { rerender } = render(
    <MediaTile
      author="a b"
      item={item}
      post={{ ...savedPost, favorite: false }}
      active
      onOpen={open}
      favorite={null}
    />,
  )
  const button = screen.getByRole('button', { name: 'Open Saved post, removed by the author' })
  expect(button.querySelector('img')).toHaveAttribute('src', '/media/a%20b/folder/thumb%20%231.png')
  expect(button.querySelector('[data-art]')).toHaveClass('opacity-70')
  expect(screen.getByTitle('Played to the end')).toBeVisible()
  expect(button.querySelector('[data-playback-progress]')).toBeNull()
  rerender(
    <MediaTile
      author="a b"
      item={item}
      post={savedPost}
      active={false}
      onOpen={open}
      favorite={null}
    />,
  )
  expect(button).toHaveAttribute('tabindex', '-1')
  fireEvent.click(button)
  expect(open).not.toHaveBeenCalled()
})

test('audio titles stay above dark cover art and use a clear fallback when unnamed', () => {
  const item = {
    ...savedVideo,
    kind: 'audio' as const,
    title: 'A track',
    duration_s: null,
    position_s: null,
  }
  const { rerender } = render(
    <MediaTile
      author="studio"
      item={item}
      post={{ ...savedPost, cover_path: 'cover.png' }}
      active
      onOpen={vi.fn()}
      favorite={null}
    />,
  )
  const button = screen.getByRole('button', { name: 'Play A track' })
  expect(button).toHaveClass('bg-slate-900')
  expect(button.querySelector('img')).toHaveClass('opacity-40')
  expect(button.querySelector('img')).toHaveAttribute('src', '/media/studio/cover.png')
  expect(screen.queryByTitle(/played/)).not.toBeInTheDocument()
  rerender(
    <MediaTile
      author="studio"
      item={{ ...item, title: null, duration_s: 0, position_s: 1 }}
      post={{ ...savedPost, title: ' ', cover_path: null }}
      active
      onOpen={vi.fn()}
      favorite={null}
    />,
  )
  expect(screen.getByRole('button', { name: 'Play Untitled post' })).toBeVisible()
  expect(screen.getByText('0:00')).toBeVisible()
  expect(screen.queryByTitle(/played/)).not.toBeInTheDocument()
})

test('clamps playback progress and leaves an unknown video duration unlabeled', () => {
  const { rerender } = render(
    <MediaTile
      author="studio"
      item={{ ...savedVideo, position_s: 200 }}
      post={savedPost}
      active
      onOpen={vi.fn()}
      favorite={null}
    />,
  )
  expect(screen.getByTitle('100% played').firstElementChild).toHaveStyle({ width: '100%' })
  rerender(
    <MediaTile
      author="studio"
      item={{ ...savedVideo, duration_s: null }}
      post={savedPost}
      active
      onOpen={vi.fn()}
      favorite={null}
    />,
  )
  expect(screen.queryByText('1:40')).not.toBeInTheDocument()
})

test('section rows distinguish missing current pieces from retained removed copies', () => {
  const { rerender } = render(<MediaSection row={{ kind: 'missing', count: 1, first: true }} />)
  expect(screen.getByText('1 piece of this view is not downloaded.')).toHaveStyle({
    height: '56px',
  })
  rerender(<MediaSection row={{ kind: 'missing', count: 12, first: false }} />)
  expect(screen.getByText('12 more pieces of this view are not downloaded.')).toBeVisible()
  rerender(<MediaSection row={{ kind: 'removed', count: 12, first: false }} />)
  const title = screen.getByRole('heading', { name: 'Removed by the author · 12' })
  expect(title.parentElement).toHaveClass('border-t')
  expect(screen.getByText('Your copies stay on disk.')).toBeVisible()
  rerender(<MediaSection row={{ kind: 'removed', count: 12, first: true }} />)
  expect(title.parentElement).not.toHaveClass('border-t')
})
