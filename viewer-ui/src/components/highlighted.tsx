import type { SearchRun } from '@/lib/api.gen'

type HighlightedProps = { runs?: SearchRun[] | null | undefined; text?: string }

/** Search fragments remain text, including markup supplied by an author. */
export function Highlighted({ runs, text }: HighlightedProps) {
  if (!runs?.some((run) => run.text.length > 0)) return text ?? null
  return runs.map((run, index) =>
    run.matched ? (
      <mark key={index} className="search-hit">
        {run.text}
      </mark>
    ) : (
      <span key={index}>{run.text}</span>
    ),
  )
}
