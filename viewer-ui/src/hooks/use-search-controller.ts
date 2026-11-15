import { useEffect, useEffectEvent, useRef, useState } from 'react'

const DEBOUNCE_MS = 200

export type SearchController = {
  text: string
  setText: (text: string) => void
  /** Clear filters without publishing a second search navigation. */
  reset: () => void
}

type SearchControllerOptions = {
  value: string
  onSearch: (text: string) => void
  active: boolean
  resetRevision?: number
  navigationRevision?: number | undefined
}

/** The draft follows URL navigation and survives changes in sidebar placement. */
export function useSearchController({
  value,
  onSearch,
  active,
  resetRevision = 0,
  navigationRevision = 0,
}: SearchControllerOptions): SearchController {
  const [text, setText] = useState(value)
  const [clearRevision, setClearRevision] = useState(0)
  const sent = useRef(value)
  const lastReset = useRef(resetRevision)
  const lastNavigation = useRef(navigationRevision)

  useEffect(() => {
    const cleared = lastReset.current !== resetRevision
    const navigated = lastNavigation.current !== navigationRevision
    lastReset.current = resetRevision
    lastNavigation.current = navigationRevision
    if (!cleared && !navigated && value === sent.current) return
    const next = cleared ? '' : value
    sent.current = next
    setText(next)
  }, [value, resetRevision, navigationRevision])

  const send = useEffectEvent((next: string) => {
    if (!active) return
    sent.current = next
    onSearch(next)
  })

  useEffect(() => {
    if (!active || text === sent.current) return
    const timer = window.setTimeout(() => send(text), DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [text, active, resetRevision, navigationRevision, clearRevision])

  return {
    text,
    setText,
    reset: () => {
      sent.current = ''
      setText('')
      setClearRevision((revision) => revision + 1)
    },
  }
}
