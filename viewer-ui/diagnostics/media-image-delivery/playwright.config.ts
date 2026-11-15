import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from '@playwright/test'

import base from '../../playwright.config'
import { REPORT_ROOT, selectedCell } from './protocol.mjs'

const directory = path.join(REPORT_ROOT, selectedCell().id)
const shared = { ...base }
delete shared.globalSetup

export default defineConfig({
  ...shared,
  testDir: fileURLToPath(new URL('.', import.meta.url)),
  testMatch: 'slow-media.spec.ts',
  workers: 1,
  retries: 0,
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  reporter: [['list'], ['json', { outputFile: path.join(directory, 'results.json') }]],
  outputDir: path.join(directory, 'artifacts'),
})
