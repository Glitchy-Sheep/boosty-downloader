import { Search, X } from 'lucide-react'
import { useEffect, useEffectEvent, useRef, useState, type RefObject } from 'react'

import { useTabActive } from '@/lib/author-tab'

const DEBOUNCE_MS = 200

type SearchBoxProps = {
  value: string
  onSearch: (text: string) => void
  resetRevision?: number
  navigationRevision?: number | undefined
  inputRef?: RefObject<HTMLInputElement | null> | undefined
}

/** Search follows the URL, publishing new text after typing pauses. */
export function SearchBox({
  value,
  onSearch,
  resetRevision = 0,
  navigationRevision = 0,
  inputRef,
}: SearchBoxProps) {
  const active = useTabActive()
  const localInput = useRef<HTMLInputElement>(null)
  const input = inputRef ?? localInput
  const [text, setText] = useState(value)
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
  }, [text, active, resetRevision, navigationRevision])

  return (
    <div className="relative">
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
      />
      <input
        ref={input}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Escape') return
          if (text) setText('')
          else event.currentTarget.blur()
        }}
        placeholder="Search posts..."
        aria-label="Search posts"
        aria-keyshortcuts={inputRef ? '/' : undefined}
        className="peer h-9 w-full min-w-0 rounded-lg border border-input bg-background py-1 pr-9 pl-8 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
      />
      {inputRef && !text && (
        <kbd
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded border px-1.5 text-xs text-muted-foreground peer-focus:hidden md:block"
        >
          /
        </kbd>
      )}
      {text && (
        <button
          type="button"
          aria-label="Clear the search"
          onClick={() => {
            setText('')
            input.current?.focus()
          }}
          className="absolute top-1/2 right-2 grid size-5 -translate-y-1/2 place-items-center rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <X aria-hidden="true" className="size-3.5" />
        </button>
      )}
    </div>
  )
}
