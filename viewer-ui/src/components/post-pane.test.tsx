import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { PostPane } from '@/components/post-pane'

test('retains reader scrolling across content updates and resets only for another post or author', () => {
  const view = render(
    <PostPane author="studio" postId="one">
      Saved text
    </PostPane>,
  )
  const pane = screen.getByRole('region', { name: 'Selected post' })
  pane.scrollTop = 120
  view.rerender(
    <PostPane author="studio" postId="one">
      Updated content
    </PostPane>,
  )
  expect(pane.scrollTop).toBe(120)
  view.rerender(
    <PostPane author="studio" postId="two">
      Another post
    </PostPane>,
  )
  expect(screen.getByRole('region', { name: 'Selected post' })).toBe(pane)
  expect(pane.scrollTop).toBe(0)
  pane.scrollTop = 470
  view.rerender(
    <PostPane author="other" postId="two">
      Another author
    </PostPane>,
  )
  expect(screen.getByRole('region', { name: 'Selected post' })).toBe(pane)
  expect(pane.scrollTop).toBe(0)
})
