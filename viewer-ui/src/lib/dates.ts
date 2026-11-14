const dayMonth = new Intl.DateTimeFormat('en-US', { day: 'numeric', month: 'short', timeZone: 'UTC' })
const monthYear = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })

/** Compact UTC date for rows grouped under a month and year. */
export function formatDay(iso: string): string {
  const parts = dayMonth.formatToParts(new Date(iso))
  const day = parts.find(part => part.type === 'day')?.value ?? ''
  const month = parts.find(part => part.type === 'month')?.value ?? ''
  return `${day} ${month}`
}

export function formatDate(iso: string): string {
  return `${formatDay(iso)} ${new Date(iso).getUTCFullYear()}`
}

export function formatMonth(iso: string): string {
  return monthYear.format(new Date(iso))
}

/** Match the API's UTC calendar-month keys. */
export function monthKey(iso: string): string {
  return new Date(iso).toISOString().slice(0, 7)
}
