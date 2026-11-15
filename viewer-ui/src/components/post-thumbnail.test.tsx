import { fireEvent, render } from '@testing-library/react'
import { expect, test } from 'vitest'

import { PostThumbnail } from '@/components/post-thumbnail'
import type { MediaCounts } from '@/lib/api.gen'
import { savedRow } from '@/test/post-fixtures'

type ThumbnailCase = { name: string; counts: MediaCounts; icon: string }
const cases: ThumbnailCase[] = [
  {
    name: 'audio',
    counts: { videos: 0, audio: 1, images: 0, files: 0 },
    icon: 'lucide-audio-lines',
  },
  { name: 'photo', counts: { videos: 0, audio: 0, images: 1, files: 0 }, icon: 'lucide-image' },
  {
    name: 'attachment',
    counts: { videos: 0, audio: 0, images: 0, files: 1 },
    icon: 'lucide-paperclip',
  },
  { name: 'text', counts: { videos: 0, audio: 0, images: 0, files: 0 }, icon: 'lucide-file-text' },
]

test.each(cases)(
  'an unavailable $name thumbnail retains its content icon and locked state',
  ({ counts, icon }) => {
    const { container, rerender } = render(
      <PostThumbnail author="studio" post={{ ...savedRow, counts, access: 'locked' }} />,
    )
    const image = container.querySelector('img')!
    fireEvent.error(image)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector(`.${icon}`)).toHaveClass('opacity-40')
    expect(container.querySelector('.lucide-lock')).toBeInTheDocument()
    rerender(<PostThumbnail author="another !#" post={{ ...savedRow, counts, access: 'open' }} />)
    expect(container.querySelector('img')).toHaveAttribute(
      'src',
      `/thumbs/another%20%21%23/${savedRow.id}`,
    )
    expect(container.querySelector('.lucide-lock')).toBeNull()
  },
)
