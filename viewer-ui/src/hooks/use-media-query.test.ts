import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { useMediaQuery } from '@/hooks/use-media-query'

afterEach(() => vi.unstubAllGlobals())

test('reads the first viewport, observes changes and removes old subscriptions', () => {
  const desktop = new EventTarget()
  const mobile = new EventTarget()
  let matches = true
  const addDesktop = vi.spyOn(desktop, 'addEventListener')
  const removeDesktop = vi.spyOn(desktop, 'removeEventListener')
  const removeMobile = vi.spyOn(mobile, 'removeEventListener')
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() {
      return query === 'desktop' && matches
    },
    addEventListener: (listener: string, callback: EventListener) =>
      (query === 'desktop' ? desktop : mobile).addEventListener(listener, callback),
    removeEventListener: (listener: string, callback: EventListener) =>
      (query === 'desktop' ? desktop : mobile).removeEventListener(listener, callback),
  }))
  const hook = renderHook(({ query }) => useMediaQuery(query), {
    initialProps: { query: 'desktop' },
  })
  expect(hook.result.current).toBe(true)
  act(() => {
    matches = false
    desktop.dispatchEvent(new Event('change'))
  })
  expect(hook.result.current).toBe(false)
  hook.rerender({ query: 'mobile' })
  expect(removeDesktop).toHaveBeenCalledExactlyOnceWith('change', addDesktop.mock.calls[0]?.[1])
  hook.unmount()
  expect(removeMobile).toHaveBeenCalledOnce()
})
