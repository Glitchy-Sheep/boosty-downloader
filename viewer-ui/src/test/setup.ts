import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class implements ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.stubGlobal('matchMedia', (media: string): MediaQueryList => ({
    matches: ['(hover: hover)', '(min-width: 640px)', '(min-width: 768px)'].includes(media),
    media,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => true,
  }))
})

// Vitest uses explicit imports, so Testing Library does not register cleanup.
afterEach(cleanup)
