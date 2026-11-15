/** Fail at the fixture boundary when a scenario's required value is absent. */
export function requireFixture<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('Expected fixture value to exist')
  return value
}
