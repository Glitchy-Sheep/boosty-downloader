import { afterEach, describe, expect, test, vi } from 'vitest'

import { deviceSizeBase, formatCount, formatSize, plural } from '@/lib/format'

type SizeCase = {
  bytes: number
  decimal: string
  binary: string
}

const SIZE_CASES: SizeCase[] = [
  { bytes: 999, decimal: '999 B', binary: '999 B' },
  { bytes: 1_000, decimal: '1 KB', binary: '1000 B' },
  { bytes: 1_023, decimal: '1.02 KB', binary: '1023 B' },
  { bytes: 1_024, decimal: '1.02 KB', binary: '1 KB' },
  { bytes: 999_499, decimal: '999 KB', binary: '976 KB' },
  { bytes: 999_500, decimal: '1 MB', binary: '976 KB' },
  { bytes: 1_023_488, decimal: '1.02 MB', binary: '0.976 MB' },
  { bytes: 1_048_576, decimal: '1.05 MB', binary: '1 MB' },
  { bytes: 1_000_000_000, decimal: '1 GB', binary: '954 MB' },
  { bytes: 1_073_741_824, decimal: '1.07 GB', binary: '1 GB' },
  { bytes: 263_049_070_956, decimal: '263 GB', binary: '245 GB' },
  { bytes: 1_500_000_000_000, decimal: '1.5 TB', binary: '1.36 TB' },
]

afterEach(() => vi.unstubAllGlobals())

describe('formatSize', () => {
  test.each(SIZE_CASES)('formats $bytes bytes at both device bases', ({ bytes, decimal, binary }) => {
    expect(formatSize(bytes, 1000)).toBe(decimal)
    expect(formatSize(bytes, 1024)).toBe(binary)
  })

  test('distinguishes a known empty file from an unknown size', () => {
    expect(formatSize(0, 1000)).toBe('0 B')
    expect(formatSize(0, 1024)).toBe('0 B')
    expect(formatSize(null, 1000)).toBe('')
    expect(formatSize(null, 1024)).toBe('')
  })

  test('promotes rounded thousands instead of showing a four-digit unit', () => {
    expect(formatSize(999_960, 1000)).toBe('1 MB')
    expect(formatSize(1_024_000, 1024)).toBe('0.977 MB')
  })

  test('uses the current device base unless the caller supplies one', () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' })
    expect(formatSize(1_000_000_000)).toBe('954 MB')
    expect(formatSize(1_000_000_000, 1000)).toBe('1 GB')
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X)' })
    expect(formatSize(1_000_000_000)).toBe('1 GB')
  })
})

describe('deviceSizeBase', () => {
  test('matches Explorer when the browser identifies Windows', () => {
    expect(deviceSizeBase('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe(1024)
  })

  test.each(['Macintosh', 'Linux', 'iPhone', 'Android', ''])('uses decimal units for %s', (userAgent) => {
    expect(deviceSizeBase(userAgent)).toBe(1000)
  })

  test('works without a browser navigator', () => {
    vi.stubGlobal('navigator', undefined)
    expect(deviceSizeBase()).toBe(1000)
  })
})

test('formats readable counts and both regular and explicit plurals', () => {
  expect(formatCount(1_200)).toBe('1,200')
  expect(plural(0, 'post')).toBe('0 posts')
  expect(plural(1, 'post')).toBe('1 post')
  expect(plural(1_200, 'post')).toBe('1,200 posts')
  expect(plural(2, 'copy', 'copies')).toBe('2 copies')
})
