export type SizeBase = 1000 | 1024

const SIZE_UNITS = ['KB', 'MB', 'GB', 'TB', 'PB', 'EB'] as const
const threeDigits = new Intl.NumberFormat('en-US', { maximumSignificantDigits: 3 })

export function formatCount(count: number): string {
  return count.toLocaleString('en-US')
}

/** Format a count with its singular or plural noun. */
export function plural(count: number, one: string, many = `${one}s`): string {
  const noun = count === 1 ? one : many
  return `${formatCount(count)} ${noun}`
}

/** Explorer counts 1024 bytes per KB; the other supported file managers use 1000. */
export function deviceSizeBase(userAgent = globalThis.navigator?.userAgent ?? ''): SizeBase {
  if (userAgent.includes('Windows')) return 1024
  return 1000
}

/** Format a nonnegative byte count to three significant digits; null has no label. */
export function formatSize(bytes: number | null, base: SizeBase = deviceSizeBase()): string {
  if (bytes === null) return ''
  if (bytes < base) return `${bytes} B`
  let value = bytes / base
  let unit = 0
  // Both bases promote a rounded 1000: 1000 binary KB reads as 0.977 MB.
  while (Number(value.toPrecision(3)) >= 1000 && unit < SIZE_UNITS.length - 1) {
    value /= base
    unit += 1
  }
  return `${threeDigits.format(value)} ${SIZE_UNITS[unit]}`
}
