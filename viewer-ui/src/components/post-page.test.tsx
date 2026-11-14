import { createEvent, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PostPage, type PostPageProps } from '@/components/post-page'
import type { PostDetail } from '@/lib/api.gen'
import { filtersSearchParams, type Filters } from '@/lib/filters'

const post: PostDetail = {
  id: 'post-1',
  title: 'First post',
  created_at: '2026-11-01T01:00:00+03:00',
  access: 'open',
  counts: { images: 2, videos: 1, files: 0, audio: 0 },
  cover_path: null,
  favorite: false,
  match: null,
  missing_media: 0,
  seen: false,
  tier: null,
  updated: false,
  body_html: '<p>Saved body</p>',
  boosty_url: 'https://boosty.to/author/posts/post-1',
  has_folder: true,
  media: [],
  post_price_rub: null,
  tier_price_rub: null,
  tags: ['art', 'draft'],
}

function pageProps(overrides: Partial<PostPageProps> = {}): PostPageProps {
  return {
    author: 'author',
    post,
    filters: {},
    posts: undefined,
    listPending: false,
    favoritePending: false,
    favoriteError: null,
    onFavorite: vi.fn(),
    onTag: vi.fn(),
    onPost: vi.fn(),
    postHref: (id) => `#${id}`,
    children: <p>Saved body</p>,
    ...overrides,
  }
}

describe('PostPage', () => {
  it('renders plain metadata, a UTC date and a safe external link', () => {
    const title = '<script>alert(1)</script>'
    const tag = '<img src=x onerror=alert(1)>'
    const { container } = render(
      <PostPage {...pageProps({ post: { ...post, title, tags: [tag] } })} />,
    )
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(title)
    expect(screen.getByRole('button', { name: `#${tag}` })).toBeVisible()
    expect(container.querySelector('script, img[src="x"]')).toBeNull()
    expect(screen.getByText('31 Oct 2026')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Boosty' })).toHaveAttribute('href', post.boosty_url)
    expect(screen.getByRole('link', { name: 'Boosty' })).toHaveAttribute('rel', 'noreferrer')
    expect(screen.queryByRole('button', { name: /seen/i })).not.toBeInTheDocument()
  })

  it.each(['javascript:alert(1)', 'data:text/html,hello', '//boosty.to/author', 'broken link'])(
    'rejects unsafe or nonabsolute Boosty metadata: %s',
    (boosty_url) => {
      render(
        <PostPage
          {...pageProps({
            post: { ...post, boosty_url, access: 'locked', body_html: '', has_folder: false },
          })}
        />,
      )
      expect(screen.queryByRole('link')).not.toBeInTheDocument()
    },
  )

  it('shows an untitled fallback and reports the selected tag without changing other filters itself', () => {
    const onTag = vi.fn()
    render(
      <PostPage
        {...pageProps({
          post: { ...post, title: '  ', tags: ['art', 'art', 'draft'] },
          filters: { tag: 'art', q: 'saved', fav: 1 },
          onTag,
        })}
      />,
    )
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Untitled post')
    expect(screen.getAllByRole('button', { name: '#art' })).toHaveLength(1)
    expect(screen.getByRole('button', { name: '#art' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '#draft' })).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(screen.getByRole('button', { name: '#draft' }))
    expect(onTag).toHaveBeenCalledExactlyOnceWith('draft')
  })

  it('uses the real favorite action, pending state and failure message', () => {
    const onFavorite = vi.fn()
    const props = pageProps({ onFavorite })
    const { rerender } = render(<PostPage {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add to favorites' }))
    expect(onFavorite).toHaveBeenCalledOnce()
    rerender(<PostPage {...props} post={{ ...post, favorite: true }} favoritePending />)
    expect(screen.getByRole('button', { name: 'Remove from favorites' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Remove from favorites' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Remove from favorites' }))
    expect(onFavorite).toHaveBeenCalledOnce()
    rerender(<PostPage {...props} favoriteError="Could not save the favorite." />)
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save the favorite.')
    expect(screen.getByRole('button', { name: 'Add to favorites' })).toBeEnabled()
  })

  it.each([true, false])(
    'keeps nonempty saved body after access becomes locked, has_folder=%s',
    (has_folder) => {
      render(<PostPage {...pageProps({ post: { ...post, access: 'locked', has_folder } })} />)
      expect(screen.getByText('Saved body')).toBeVisible()
      expect(screen.getByText(/Previously saved content remains available/)).toBeVisible()
      expect(screen.queryByRole('region', { name: 'Locked post' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /favorites/ })).not.toBeInTheDocument()
    },
  )

  it('retains a saved empty folder instead of claiming the post was never saved', () => {
    render(
      <PostPage
        {...pageProps({
          post: { ...post, access: 'locked', body_html: '', has_folder: true },
          children: <p>This post has no text or media.</p>,
        })}
      />,
    )
    expect(screen.getByText('This post has no text or media.')).toBeVisible()
    expect(screen.queryByRole('region', { name: 'Locked post' })).not.toBeInTheDocument()
  })

  it('shows never-saved locked metadata, both prices and remote media counts', () => {
    const locked = {
      ...post,
      access: 'locked' as const,
      body_html: '  ',
      has_folder: false,
      tier: 'Studio',
      tier_price_rub: 0,
      post_price_rub: 500,
    }
    render(<PostPage {...pageProps({ post: locked })} />)
    const card = screen.getByRole('region', { name: 'Locked post' })
    expect(within(card).getByText('Studio')).toBeVisible()
    expect(within(card).getByText('Subscription price: 0 ₽ / month')).toBeVisible()
    expect(within(card).getByText('Post price: 500 ₽')).toBeVisible()
    expect(within(card).getByText('1 video')).toBeVisible()
    expect(within(card).getByText('2 photos')).toBeVisible()
    expect(within(card).getByRole('link', { name: 'Open on Boosty' })).toHaveAttribute(
      'href',
      post.boosty_url,
    )
    expect(screen.queryByText('Saved body')).not.toBeInTheDocument()
  })

  it('uses the thumbnail endpoint for a locked cover and removes failed artwork', () => {
    const locked = {
      ...post,
      access: 'locked' as const,
      body_html: '',
      has_folder: false,
      cover_path: '../../arbitrary-file',
    }
    const props = pageProps({ author: 'автор /', post: locked })
    const { container, rerender } = render(<PostPage {...props} />)
    const image = container.querySelector('img')!
    expect(image).toHaveAttribute('src', '/thumbs/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%2F/post-1')
    fireEvent.error(image)
    expect(container.querySelector('img')).toBeNull()
    rerender(<PostPage {...props} post={{ ...locked, id: 'post-2' }} />)
    expect(container.querySelector('img')).toHaveAttribute(
      'src',
      '/thumbs/%D0%B0%D0%B2%D1%82%D0%BE%D1%80%20%2F/post-2',
    )
  })

  it('passes full filter URLs to pager anchors and preserves modified clicks', () => {
    const previous = { ...post, id: 'before', title: 'Earlier in the list' }
    const next = { ...post, id: 'after', title: 'Later in the list' }
    const filters: Filters = {
      q: 'body',
      kind: 'videos',
      unseen: 1,
      fav: 1,
      tag: 'art',
      locked: 1,
      incomplete: 1,
      order: 'oldest',
    }
    const onPost = vi.fn()
    render(
      <PostPage
        {...pageProps({
          filters,
          posts: { rows: [previous, post, next], months: [], total: 3 },
          onPost,
          postHref: (id) => `#${id}?${filtersSearchParams(filters)}`,
        })}
      />,
    )
    const navigation = screen.getByRole('navigation', { name: 'Post navigation' })
    const link = within(navigation).getByRole('link', { name: 'Next: Later in the list' })
    expect(link).toHaveAttribute(
      'href',
      '#after?q=body&kind=videos&unseen=1&fav=1&tag=art&locked=1&incomplete=1&order=oldest',
    )
    const modified = createEvent.click(link, { button: 0, ctrlKey: true })
    fireEvent(link, modified)
    expect(modified.defaultPrevented).toBe(false)
    expect(onPost).not.toHaveBeenCalled()
    const ordinary = createEvent.click(link, { button: 0 })
    fireEvent(link, ordinary)
    expect(ordinary.defaultPrevented).toBe(true)
    expect(onPost).toHaveBeenCalledExactlyOnceWith('after')
    expect(navigation.querySelector('kbd')).toBeNull()
  })

  it('removes stale pager destinations during a filter update', () => {
    const props = pageProps({
      posts: { rows: [post, { ...post, id: 'next' }], months: [], total: 2 },
    })
    const { rerender } = render(<PostPage {...props} />)
    expect(screen.getByRole('navigation', { name: 'Post navigation' })).toBeVisible()
    rerender(<PostPage {...props} listPending />)
    expect(screen.queryByRole('navigation', { name: 'Post navigation' })).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Updating post navigation...')
  })
})
