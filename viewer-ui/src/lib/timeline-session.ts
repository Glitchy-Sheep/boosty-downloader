import type { RefObject } from 'react'

import type { TimelineAnchor } from '@/lib/timeline-anchor'

/** The reader's place in one selected and filtered post timeline. */
export type TimelineSnapshot = {
  listKey: string
  currentId: string | undefined
  anchor: TimelineAnchor | null
}

export type TimelineSession = RefObject<TimelineSnapshot | null>
