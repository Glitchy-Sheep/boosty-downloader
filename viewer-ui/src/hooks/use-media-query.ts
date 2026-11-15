import { useMemo, useSyncExternalStore } from 'react'

/** Read the viewport on the first render and subscribe to breakpoint changes. */
export function useMediaQuery(query: string): boolean {
  const source = useMemo(() => {
    const media = window.matchMedia(query)
    return {
      subscribe: (onChange: () => void) => {
        media.addEventListener('change', onChange)
        return () => media.removeEventListener('change', onChange)
      },
      snapshot: () => media.matches,
    }
  }, [query])
  return useSyncExternalStore(source.subscribe, source.snapshot)
}
