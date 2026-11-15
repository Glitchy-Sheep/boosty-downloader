import { useLayoutEffect, useState, type RefObject } from 'react'
import { flushSync } from 'react-dom'

type ElementWidthOptions = { synchronous?: boolean }

/** A hidden element retains its last measured content width. */
export function useElementWidth(
  ref: RefObject<HTMLElement | null>,
  { synchronous = false }: ElementWidthOptions = {},
): number | null {
  const [width, setWidth] = useState<number | null>(null)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    let measured: number | null = null
    const measure = (sync: boolean): void => {
      const next = element.clientWidth
      if (next <= 0 || next === measured) return
      measured = next
      if (sync) flushSync(() => setWidth(next))
      else setWidth(next)
    }
    measure(false)
    const update = (): void => measure(synchronous)
    const observer = new ResizeObserver(update)
    observer.observe(element)
    // Anchored layouts must update before the first frame of a viewport resize.
    if (synchronous) window.addEventListener('resize', update)
    return () => {
      observer.disconnect()
      if (synchronous) window.removeEventListener('resize', update)
    }
  }, [ref, synchronous])
  return width
}
