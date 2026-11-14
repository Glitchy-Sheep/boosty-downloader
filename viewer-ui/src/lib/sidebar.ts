const ROWS_SMALL_WIDTH = 260
const ROWS_FULL_WIDTH = 510
const PADDING_FULL_WIDTH = 360
const ROW_PADDING_Y = 10
const META_HEIGHT = 16
const TITLE_GAP = 4
const SNIPPET_HEIGHT = 32

export type RowMetrics = {
  height: number
  snippetHeight: number
  coverWidth: number
  gap: number
  padX: number
  titleSize: number
  titleLeading: number
  titleLines: number
}

function lerp(from: number, to: number, fraction: number): number {
  return from + (to - from) * fraction
}

/** Grow row contents smoothly; title, date and optional snippet fit their height. */
export function rowMetrics(width: number): RowMetrics {
  const boundedWidth = Math.min(Math.max(width, ROWS_SMALL_WIDTH), ROWS_FULL_WIDTH)
  const fraction = (boundedWidth - ROWS_SMALL_WIDTH) / (ROWS_FULL_WIDTH - ROWS_SMALL_WIDTH)
  const coverWidth = lerp(64, 144, fraction)
  const coverHeight = (coverWidth * 9) / 16
  const titleSize = lerp(13.5, 15, fraction)
  const titleLeading = titleSize * 1.3
  const text = 2 * titleLeading + TITLE_GAP + META_HEIGHT
  const height = Math.round(Math.max(coverHeight, text) + 2 * ROW_PADDING_Y)
  const room = height - 2 * ROW_PADDING_Y - TITLE_GAP - META_HEIGHT
  const withSnippet = text + SNIPPET_HEIGHT + TITLE_GAP
  const paddingFraction = Math.min((boundedWidth - ROWS_SMALL_WIDTH) / (PADDING_FULL_WIDTH - ROWS_SMALL_WIDTH), 1)
  return {
    height,
    snippetHeight: Math.round(Math.max(coverHeight, withSnippet) + 2 * ROW_PADDING_Y),
    coverWidth,
    gap: lerp(10, 14, fraction),
    padX: lerp(12, 16, paddingFraction),
    titleSize,
    titleLeading,
    titleLines: Math.min(3, Math.max(2, Math.floor(room / titleLeading))),
  }
}
