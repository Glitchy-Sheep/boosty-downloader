import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest uses explicit imports, so Testing Library does not register cleanup.
afterEach(cleanup)
