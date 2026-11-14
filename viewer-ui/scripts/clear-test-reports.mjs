import { rm } from 'node:fs/promises'

await Promise.all(
  ['../coverage/', '../reports/unit-tests.json'].map((path) =>
    rm(new URL(path, import.meta.url), { recursive: true, force: true }),
  ),
)
