import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PostBody } from '@/components/post-body'
import { TabActive } from '@/lib/author-tab'

vi.mock('@/hooks/use-post-playback', () => ({ usePostPlayback: vi.fn() }))
const defaults = {
  author: 'writer',
  postId: 'first',
  media: [],
  query: undefined,
  onClearSearch: vi.fn(),
  savePosition: vi.fn(async () => {}),
  onNavigate: vi.fn(),
}

beforeEach(() => {
  vi.clearAllMocks()
  HTMLElement.prototype.scrollIntoView = vi.fn()
})

afterEach(() => vi.useRealTimers())

describe('PostBody', () => {
  it('keeps players and listeners through search and cache renders, then removes search marks', () => {
    const html =
      '<p>Shader lesson and shader notes</p><video controls src="/media/writer/video.mp4"></video><audio controls src="/media/writer/audio.wav"></audio>'
    const { container, rerender } = render(<PostBody {...defaults} html={html} />)
    const video = container.querySelector('video')!
    const audio = container.querySelector('audio')!
    const pause = vi.fn()
    video.addEventListener('pause', pause)
    video.currentTime = 42
    rerender(<PostBody {...defaults} html={html} query="shader" media={[]} />)
    expect(container.querySelector('video')).toBe(video)
    expect(container.querySelector('audio')).toBe(audio)
    expect(video.currentTime).toBe(42)
    expect(screen.getByText('Match 1 of 2 in the text')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next match' }))
    expect(screen.getByText('Match 2 of 2 in the text')).toBeInTheDocument()
    expect(container.querySelectorAll('mark[data-current]')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Clear search in this post' }))
    expect(defaults.onClearSearch).toHaveBeenCalledOnce()
    rerender(<PostBody {...defaults} html={html} query={undefined} media={[]} />)
    expect(container.querySelector('mark')).toBeNull()
    expect(container.querySelector('video')).toBe(video)
    fireEvent.pause(video)
    expect(pause).toHaveBeenCalledOnce()
  })

  it('does not claim a title match when only the list or another field matched', () => {
    render(<PostBody {...defaults} html="<p>Different body</p>" query="absent" />)
    expect(screen.getByText('No matches in the text')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous match' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next match' })).toBeDisabled()
  })

  it('opens body images in DOM order, includes retained images and restores focus', async () => {
    const html =
      '<img src="/media/writer/first.jpg" alt="First drawing"><video poster="/media/writer/poster.jpg"></video><section class="removed-media"><img src="/media/writer/second.jpg" alt="Retained drawing"></section>'
    render(<PostBody {...defaults} html={html} />)
    const first = screen.getByRole('button', { name: 'Open image: First drawing' })
    first.focus()
    fireEvent.keyDown(first, { key: 'Enter' })
    const dialog = screen.getByRole('dialog', { name: 'Post image viewer' })
    expect(within(dialog).getByRole('img', { name: 'First drawing' })).toHaveAttribute(
      'src',
      `${location.origin}/media/writer/first.jpg`,
    )
    expect(within(dialog).getByText('1 / 2')).toBeInTheDocument()
    fireEvent.keyDown(dialog, { key: 'ArrowRight' })
    expect(within(dialog).getByRole('img', { name: 'Retained drawing' })).toBeInTheDocument()
    expect(within(dialog).getByText('2 / 2')).toBeInTheDocument()
    fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(first).toHaveFocus())
  })

  it('gives unnamed images a useful label and closes the gallery on post changes', () => {
    vi.useFakeTimers()
    const { rerender } = render(
      <PostBody {...defaults} html='<img src="/media/writer/first.jpg" alt="">' />,
    )
    const first = screen.getByRole('button', { name: 'Open image: Image 1' })
    fireEvent.click(first)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    const restoreOldFocus = vi.spyOn(first, 'focus')
    rerender(
      <PostBody
        {...defaults}
        postId="second"
        html='<p>The next post</p><button type="button">New post action</button>'
      />,
    )
    const nextAction = screen.getByRole('button', { name: 'New post action' })
    nextAction.focus()
    act(() => {
      vi.runAllTimers()
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Open image/ })).not.toBeInTheDocument()
    expect(first.isConnected).toBe(false)
    expect(restoreOldFocus).not.toHaveBeenCalled()
    expect(nextAction).toHaveFocus()
  })

  it('routes body post links without leaking filters and ignores modified clicks', () => {
    render(<PostBody {...defaults} html='<a href="/a/other/p/second?q=001#part">Other post</a>' />)
    const link = screen.getByRole('link', { name: 'Other post' })
    fireEvent.click(link)
    expect(defaults.onNavigate).toHaveBeenCalledExactlyOnceWith('/a/other/p/second?q=001#part')
    link.addEventListener('click', (event) => event.preventDefault())
    fireEvent.click(link, { ctrlKey: true })
    expect(defaults.onNavigate).toHaveBeenCalledOnce()
  })

  it('presents an empty body without fabricating content', () => {
    render(<PostBody {...defaults} html="  " />)
    expect(screen.getByText('This post has no text or media.')).toBeInTheDocument()
  })

  it('closes a hidden tab image portal without returning focus to its retained image', async () => {
    const body = (active: boolean) => (
      <TabActive value={active}>
        <PostBody {...defaults} html='<img src="/media/writer/photo.jpg" alt="Drawing">' />
      </TabActive>
    )
    const { rerender } = render(body(true))
    const trigger = screen.getByRole('button', { name: 'Open image: Drawing' })
    fireEvent.click(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    const focus = vi.spyOn(trigger, 'focus')
    rerender(body(false))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger.isConnected).toBe(true)
    expect(focus).not.toHaveBeenCalled()
    rerender(body(true))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps linked images outside the gallery and respects modified keys and gallery bounds', async () => {
    render(
      <PostBody
        {...defaults}
        html='<a href="https://example.test"><img alt="Linked" src="/linked.jpg"></a><button type="button">Authored action</button><img src="/first.jpg" alt="First"><img src="/last.jpg" alt="Last">'
      />,
    )
    expect(screen.getByRole('img', { name: 'Linked' })).not.toHaveAttribute('role', 'button')
    const trigger = screen.getByRole('button', { name: 'Open image: First' })
    fireEvent.keyDown(trigger, { key: 'Enter', ctrlKey: true })
    fireEvent.keyDown(screen.getByRole('button', { name: 'Authored action' }), { key: ' ' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.keyDown(trigger, { key: ' ' })
    const dialog = screen.getByRole('dialog')
    fireEvent.keyDown(dialog, { key: 'ArrowRight', altKey: true })
    fireEvent.keyDown(dialog, { key: 'ArrowLeft' })
    expect(within(dialog).getByText('1 / 2')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Next image' }))
    fireEvent.keyDown(dialog, { key: 'ArrowRight' })
    expect(within(dialog).getByText('2 / 2')).toBeInTheDocument()
    fireEvent.keyDown(dialog, { key: 'ArrowLeft' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Next image' }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Previous image' }))
    expect(within(dialog).getByText('1 / 2')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close image viewer' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
