/** Keep search and tag text literal; repeated keys remain visibly malformed. */
export function parseViewerSearch(search: string): Record<string, unknown> {
  const values = Object.create(null) as Record<string, unknown>
  for (const [key, value] of new URLSearchParams(search)) {
    const previous = values[key]
    if (previous === undefined) values[key] = value
    else if (Array.isArray(previous)) previous.push(value)
    else values[key] = [previous, value]
  }
  return values
}

/** The viewer uses flat scalar parameters, without JSON inside query values. */
export function stringifyViewerSearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === 'string' || typeof value === 'boolean') params.set(key, String(value))
    else if (typeof value === 'number' && Number.isFinite(value)) params.set(key, String(value))
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}
