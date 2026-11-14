import type { SearchRun } from '@/lib/api.gen'

/** Search fragments remain text, including markup supplied by an author. */
export function Highlighted({ runs, text }: { runs?: SearchRun[] | null; text?: string }) {
  if (!runs?.some(run => run.text.length > 0)) return text ?? null
  return runs.map((run, index) => run.matched
    ? <mark key={index} className="search-hit">{run.text}</mark>
    : <span key={index}>{run.text}</span>)
}
