import { createEvent, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PostRow } from '@/components/post-row'
import { PostThumbnail } from '@/components/post-thumbnail'
import type { PostRow as PostSummary } from '@/lib/api.gen'

const post: PostSummary = {
  id: 'post-1', title: 'First post', created_at: '2026-11-01T01:00:00+03:00',
  access: 'open', counts: { images: 2, videos: 1, files: 0, audio: 0 },
  cover_path: null, favorite: false, match: null, missing_media: 0,
  seen: false, tier: null, updated: false,
}

describe('PostRow', () => {
  it('shows safe text highlights and current state using UTC dates', () => {
    const unsafeTitle = '<script>alert(1)</script>'
    const unsafeSnippet = '<img src=x onerror=alert(1)>'
    const { container } = render(<PostRow author="author" post={{ ...post, title: unsafeTitle, match: { title: [{ text: unsafeTitle, matched: true }], text: [{ text: unsafeSnippet, matched: false }] } }} current href="#post" onSelect={vi.fn()} />)
    const link = screen.getByRole('link', { name: unsafeTitle })
    expect(link).toHaveAttribute('aria-current', 'page')
    expect(link).toHaveAccessibleDescription('Unseen.')
    expect(screen.getByText(unsafeSnippet)).toBeVisible()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img[src="x"]')).toBeNull()
    expect(container.querySelector('mark')).toHaveTextContent(unsafeTitle)
    expect(screen.getByText('31 Oct')).toBeVisible()
    expect(screen.getByText('2 photos')).toBeInTheDocument()
  })

  it('keeps ordinary links for modified clicks and intercepts plain selection', () => {
    const select = vi.fn()
    render(<PostRow author="author" post={post} current={false} href="#post" onSelect={select} />)
    const link = screen.getByRole('link', { name: 'First post' })
    const modified = createEvent.click(link, { button: 0, ctrlKey: true })
    fireEvent(link, modified)
    expect(modified.defaultPrevented).toBe(false)
    expect(select).not.toHaveBeenCalled()
    const ordinary = createEvent.click(link, { button: 0 })
    fireEvent(link, ordinary)
    expect(ordinary.defaultPrevented).toBe(true)
    expect(select).toHaveBeenCalledExactlyOnceWith('post-1')
  })

  it('describes locked, favorite and incomplete state without mutation controls', () => {
    render(<PostRow author="author" post={{ ...post, access: 'locked', tier: 'Studio', seen: true, favorite: true, missing_media: 2, updated: true }} current={false} href="#post" onSelect={vi.fn()} />)
    expect(screen.getByRole('link')).toHaveAccessibleDescription('Seen. Locked. Favorite. Updated since seen. 2 missing pieces.')
    expect(screen.getByText('Studio')).toBeVisible()
    expect(screen.getByText('2 missing')).toBeVisible()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it.each([
    { label: 'without search', title: '', match: null },
    { label: 'with an empty highlight list', title: '', match: { title: [], text: null } },
    { label: 'with an empty highlight fragment', title: '', match: { title: [{ text: '', matched: false }], text: null } },
    { label: 'with whitespace only', title: '  ', match: null },
  ])('names an untitled post $label', ({ title, match }) => {
    render(<PostRow author="author" post={{ ...post, title, match }} current={false} href="#post" onSelect={vi.fn()} />)
    expect(screen.getByRole('link')).toHaveAccessibleName('Untitled post')
    expect(screen.getByText('Untitled post')).toBeVisible()
  })

  it('keeps the actual title when the highlight list contains no text', () => {
    render(<PostRow author="author" post={{ ...post, match: { title: [], text: null } }} current={false} href="#post" onSelect={vi.fn()} />)
    expect(screen.getByRole('link')).toHaveAccessibleName('First post')
  })
})

describe('PostThumbnail', () => {
  it('encodes identities, replaces failed artwork and retries a changed identity', () => {
    const { container, rerender } = render(<PostThumbnail author="автор /" post={post} />)
    const image = container.querySelector('img')!
    expect(image).toHaveAttribute('src', '/thumbs/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%2F/post-1')
    fireEvent.error(image)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).not.toBeNull()
    rerender(<PostThumbnail author="автор /" post={{ ...post, id: 'next' }} />)
    expect(container.querySelector('img')).toHaveAttribute('src', '/thumbs/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%2F/next')
  })
})
