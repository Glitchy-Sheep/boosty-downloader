import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { test as base } from '@playwright/test'

import { browserMetadata } from './browser-diagnostics'

export const test = base.extend<object, { browserDiagnostics: void }>({
  browserDiagnostics: [
    async ({ browser, browserName }, provideDiagnostics, worker) => {
      const metadata = await browserMetadata(browser, browserName)
      await mkdir(worker.project.outputDir, { recursive: true })
      await writeFile(
        path.join(worker.project.outputDir, `browser-${browserName}-${worker.workerIndex}.json`),
        JSON.stringify(metadata, null, 2),
      )
      await provideDiagnostics()
    },
    { scope: 'worker', auto: true },
  ],
})
