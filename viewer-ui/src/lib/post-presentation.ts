/** Metadata URLs must be absolute web links before becoming clickable. */
export function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value)
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.href
  } catch {
    return null
  }
  return null
}

export function displayedPostTitle(title: string): string {
  return title.trim() ? title : 'Untitled post'
}
