import { LibraryBig } from 'lucide-react'

export function AppShell() {
  return (
    <div className="flex h-dvh flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-3 md:h-14 md:gap-4 md:px-4">
        <a
          href="/"
          aria-label="Boosty Library"
          className="flex shrink-0 items-center gap-2.5 rounded-md text-[15px] font-semibold tracking-tight outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className="grid size-7 place-items-center rounded-lg bg-primary text-primary-foreground">
            <LibraryBig aria-hidden="true" className="size-4" strokeWidth={2.25} />
          </span>
          <span className="hidden sm:inline">Boosty Library</span>
        </a>
        <span aria-hidden="true" className="h-5 w-px shrink-0 bg-border" />
        <nav aria-label="Library" className="flex min-w-0 items-center text-[13px]">
          <a
            href="/"
            aria-current="page"
            className="rounded-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Authors
          </a>
        </nav>
      </header>
      <main aria-label="Authors" className="min-h-0 flex-1" />
    </div>
  )
}
