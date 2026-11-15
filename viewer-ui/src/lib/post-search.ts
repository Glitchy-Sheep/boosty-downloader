export type TextRange = { start: number; end: number }
export type SearchHit = { marks: HTMLElement[] }
type FoldedText = { text: string; origins: TextRange[] }
type TextPart = TextRange & { node: Text }
type TextRun = { text: string; parts: TextPart[] }
type MarkedRange = { range: TextRange; hit: SearchHit }

// unicode61 ignores these combining accents; other combining marks separate words.
// https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_unicode2.c
const SEARCH_DIACRITIC =
  /[\u0300-\u0304\u0306-\u030c\u030f\u0311\u031b\u0323-\u0328\u032d\u032e\u0330\u0331]/u
// unicode61 simple folding also equates these lowercase letter variants.
// Keep this separate from compatibility normalization, which changes other words.
const SIMPLE_FOLD: Readonly<Record<string, string>> = {
  µ: 'μ',
  ſ: 's',
  ς: 'σ',
  ϐ: 'β',
  ϑ: 'θ',
  ϕ: 'φ',
  ϖ: 'π',
  ϰ: 'κ',
  ϱ: 'ρ',
  ϵ: 'ε',
  ẛ: 'ṡ',
  ι: 'ι',
}
const WORDS = /[\p{L}\p{N}\p{Co}]+/gu
const EXCLUDED =
  'video, audio, script, style, button, input, textarea, select, [data-page-generated], [data-page-slot], .resume-note'
const BLOCKS = new Set([
  'P',
  'DIV',
  'SECTION',
  'ARTICLE',
  'UL',
  'OL',
  'LI',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'BLOCKQUOTE',
  'PRE',
  'TABLE',
  'TR',
  'TD',
  'TH',
  'BR',
  'HR',
  'IMG',
])

function foldCharacter(character: string): string {
  if (SEARCH_DIACRITIC.test(character)) return ''
  const lower = SIMPLE_FOLD[character] ?? character.toLowerCase().replace('ё', 'е')
  if (!/^\p{Script=Latin}/u.test(lower)) return lower
  return lower.normalize('NFD').replace(/\p{M}/gu, '')
}

function fold(text: string): FoldedText {
  const result: FoldedText = { text: '', origins: [] }
  let start = 0
  for (const character of text) {
    const end = start + character.length
    const folded = foldCharacter(character)
    result.text += folded
    const previous = result.origins.at(-1)
    if (!folded && previous) previous.end = end
    for (let index = 0; index < folded.length; index++) result.origins.push({ start, end })
    start = end
  }
  return result
}

/** Literal prefix terms, with Russian yo and Latin accents folded for searching. */
export function searchWords(query: string | undefined): string[] {
  return [...new Set(fold(query ?? '').text.match(WORDS) ?? [])]
}

/** Whole words matching a prefix, with offsets in the original text. */
export function findHits(text: string, words: readonly string[]): TextRange[] {
  if (!words.length) return []
  const folded = fold(text)
  const hits: TextRange[] = []
  for (const match of folded.text.matchAll(WORDS)) {
    if (!words.some((word) => match[0].startsWith(word))) continue
    const first = folded.origins[match.index]
    const last = folded.origins[match.index + match[0].length - 1]
    if (first && last) hits.push({ start: first.start, end: last.end })
  }
  return hits
}

/** Inline formatting belongs to the same word; block boundaries and generated UI do not. */
function textRuns(root: HTMLElement): TextRun[] {
  const runs: TextRun[] = []
  let current: TextRun = { text: '', parts: [] }
  const finish = () => {
    if (current.parts.length) runs.push(current)
    current = { text: '', parts: [] }
  }
  const visit = (node: Node) => {
    if (node instanceof Text) {
      const start = current.text.length
      current.text += node.data
      current.parts.push({ node, start, end: current.text.length })
      return
    }
    if (!(node instanceof Element)) return
    if (node.matches(EXCLUDED)) {
      finish()
      return
    }
    const boundary = BLOCKS.has(node.tagName)
    if (boundary) finish()
    node.childNodes.forEach(visit)
    if (boundary) finish()
  }
  root.childNodes.forEach(visit)
  finish()
  return runs
}

function markPart(part: TextPart, range: TextRange): HTMLElement | null {
  const start = Math.max(part.start, range.start) - part.start
  const end = Math.min(part.end, range.end) - part.start
  if (start >= end) return null
  const text = part.node.splitText(start)
  text.splitText(end - start)
  const mark = document.createElement('mark')
  mark.className = 'search-hit'
  mark.dataset.postSearchHit = ''
  text.replaceWith(mark)
  mark.append(text)
  return mark
}

/** Mark authored text without replacing links, images or native media players. */
export function markHits(root: HTMLElement, words: readonly string[]): SearchHit[] {
  unmarkHits(root)
  const hits: SearchHit[] = []
  for (const run of textRuns(root)) {
    const markedRanges: MarkedRange[] = findHits(run.text, words).map((range) => ({
      range,
      hit: { marks: [] },
    }))
    const descending = markedRanges.toReversed()
    for (const part of run.parts) {
      // Descending offsets keep the remaining text positions valid after splitting.
      for (const { range, hit } of descending) {
        const mark = markPart(part, range)
        if (mark) hit.marks.push(mark)
      }
    }
    hits.push(...markedRanges.map(({ hit }) => hit))
  }
  return hits
}

export function unmarkHits(root: HTMLElement): void {
  const parents = new Set<Node>()
  for (const mark of root.querySelectorAll('mark[data-post-search-hit]')) {
    if (mark.parentNode) parents.add(mark.parentNode)
    mark.replaceWith(...mark.childNodes)
  }
  for (const parent of parents) parent.normalize()
}
