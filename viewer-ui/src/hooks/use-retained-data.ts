import { useState } from 'react'

/** A hidden pane keeps its rendered data even if its inactive query is collected. */
export function useRetainedData<T>(data: T | undefined): T | undefined {
  const [retained, setRetained] = useState(data)
  if (data !== undefined && data !== retained) setRetained(data)
  return data ?? retained
}
