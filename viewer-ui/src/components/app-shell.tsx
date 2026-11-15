import { LibraryBig } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { HeaderSlots } from '@/lib/header-slots'

export function AppShell({
  children,
  isAuthorsPage = true,
  footer,
}: {
  children?: ReactNode
  isAuthorsPage?: boolean
  footer?: ReactNode
}) {
  const [start, setStart] = useState<HTMLElement | null>(null)
  const [tabs, setTabs] = useState<HTMLElement | null>(null)
  const slots = useMemo(() => ({ start, tabs }), [start, tabs])
  return (
    <div className="flex h-dvh flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-3 md:h-14 md:gap-4 md:px-4">
        <div ref={setStart} className="flex shrink-0 items-center empty:hidden" />
        <Link
          to="/"
          aria-label="Boosty Library"
          className="flex shrink-0 items-center gap-2.5 rounded-md text-[15px] font-semibold tracking-tight outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className="grid size-7 place-items-center rounded-lg bg-primary text-primary-foreground">
            <LibraryBig aria-hidden="true" className="size-4" strokeWidth={2.25} />
          </span>
          <span className="hidden sm:inline">Boosty Library</span>
        </Link>
        <span aria-hidden="true" className="h-5 w-px shrink-0 bg-border" />
        <nav aria-label="Library" className="flex min-w-0 items-center text-[13px]">
          <Link
            to="/"
            aria-current={isAuthorsPage ? 'page' : undefined}
            className="rounded-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Authors
          </Link>
        </nav>
        <div ref={setTabs} className="contents" />
      </header>
      <main aria-label={isAuthorsPage ? 'Authors' : 'Library'} className="min-h-0 flex-1">
        <HeaderSlots value={slots}>{children}</HeaderSlots>
      </main>
      {footer}
    </div>
  )
}
