import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { buildQualitySummary } from './quality-report.mjs'

const passedTests = {
  numTotalTests: 5,
  numPassedTests: 3,
  numFailedTests: 0,
  numPendingTests: 1,
  numTodoTests: 1,
  success: true,
  startTime: 1000,
  testResults: [{ endTime: 1500 }, { endTime: 2250 }],
}
const coverage = {
  total: {
    statements: { total: 10, covered: 8, pct: 80 },
    branches: { total: 5, covered: 3, pct: 60 },
    functions: { total: 4, covered: 4, pct: 100 },
    lines: { total: 9, covered: 7, pct: 77.77 },
  },
}

/** @param {import('node:test').TestContext} context @returns {Promise<string>} */
async function reportDirectory(context) {
  const directory = await mkdtemp(join(tmpdir(), 'boosty-quality-report-'))
  context.after(() => rm(directory, { recursive: true, force: true }))
  await Promise.all([mkdir(join(directory, 'reports')), mkdir(join(directory, 'coverage'))])
  return directory
}

/** @param {string} directory @param {unknown} tests @param {unknown} metrics */
async function writeReports(directory, tests = passedTests, metrics = coverage) {
  await Promise.all([
    writeFile(join(directory, 'reports/unit-tests.json'), JSON.stringify(tests)),
    writeFile(join(directory, 'coverage/coverage-summary.json'), JSON.stringify(metrics)),
  ])
}

await test('reports actual test counts, elapsed test time and all four coverage metrics', async (context) => {
  const directory = await reportDirectory(context)
  await writeReports(directory)

  const summary = await buildQualitySummary(directory)

  assert.match(summary, /Unit test result: \*\*passed\*\*\. Test duration: 1\.25 s\./)
  assert.match(summary, /\| 5 \| 3 \| 0 \| 1 \| 1 \|/)
  assert.match(summary, /\| statements \| 8 \| 10 \| 80\.00% \|/)
  assert.match(summary, /\| branches \| 3 \| 5 \| 60\.00% \|/)
  assert.match(summary, /\| functions \| 4 \| 4 \| 100\.00% \|/)
  assert.match(summary, /\| lines \| 7 \| 9 \| 77\.77% \|/)
})

await test('preserves failed results and available coverage after failed assertions', async (context) => {
  const directory = await reportDirectory(context)
  await writeReports(directory, {
    ...passedTests,
    numPassedTests: 2,
    numFailedTests: 1,
    success: false,
  })

  const summary = await buildQualitySummary(directory)

  assert.match(summary, /Unit test result: \*\*failed\*\*/)
  assert.match(summary, /\| 5 \| 2 \| 1 \| 1 \| 1 \|/)
  assert.match(summary, /\| statements \| 8 \| 10 \| 80\.00% \|/)
})

await test('does not call a run successful when the runner failed outside an assertion', async (context) => {
  const directory = await reportDirectory(context)
  await writeReports(directory, { ...passedTests, success: false })

  const summary = await buildQualitySummary(directory)

  assert.match(summary, /Unit test result: \*\*failed\*\*/)
  assert.doesNotMatch(summary, /\*\*passed\*\*/)
})

await test('missing reports are unavailable rather than empty successes', async (context) => {
  const directory = await reportDirectory(context)

  const summary = await buildQualitySummary(directory)

  assert.match(summary, /Unit tests: unavailable \(missing report\)/)
  assert.match(summary, /Coverage: unavailable \(missing report\)/)
  assert.doesNotMatch(summary, /\*\*passed\*\*|0\.00%|\| 0 \|/)
})

await test('malformed JSON is reported without printing arbitrary report contents', async (context) => {
  const directory = await reportDirectory(context)
  await writeFile(join(directory, 'reports/unit-tests.json'), 'untrusted invalid contents')
  await writeFile(join(directory, 'coverage/coverage-summary.json'), '{')

  const summary = await buildQualitySummary(directory)

  assert.match(summary, /Unit tests: unavailable \(invalid JSON\)/)
  assert.match(summary, /Coverage: unavailable \(invalid JSON\)/)
  assert.doesNotMatch(summary, /untrusted invalid contents/)
})

await test('invalid test fields and impossible coverage counts stay unavailable', async (context) => {
  const directory = await reportDirectory(context)
  await writeReports(
    directory,
    { ...passedTests, numTotalTests: '5' },
    {
      total: {
        ...coverage.total,
        statements: { total: 10, covered: 11, pct: 110 },
        branches: { total: 5, covered: -1, pct: -20 },
      },
    },
  )

  const summary = await buildQualitySummary(directory)

  assert.match(summary, /Unit tests: unavailable \(invalid report fields\)/)
  assert.match(summary, /\| statements \| unavailable \| unavailable \| unavailable \|/)
  assert.match(summary, /\| branches \| unavailable \| unavailable \| unavailable \|/)
  assert.match(summary, /\| functions \| 4 \| 4 \| 100\.00% \|/)
})

await test('a run with no tests cannot appear as a passed run or invent a duration', async (context) => {
  const directory = await reportDirectory(context)
  await writeReports(directory, {
    ...passedTests,
    numTotalTests: 0,
    numPassedTests: 0,
    numPendingTests: 0,
    numTodoTests: 0,
    testResults: [],
  })

  const summary = await buildQualitySummary(directory)

  assert.match(summary, /Unit test result: \*\*no tests\*\*\. Test duration: unavailable\./)
})

await test('the CLI prints its report and appends it to the GitHub step summary', async (context) => {
  const directory = await reportDirectory(context)
  const summaryPath = join(directory, 'step-summary.md')
  await writeReports(directory)
  await writeFile(summaryPath, 'Previous step\n')
  const script = fileURLToPath(new URL('./quality-report.mjs', import.meta.url))

  const result = spawnSync(process.execPath, [script], {
    cwd: directory,
    encoding: 'utf8',
    env: { ...process.env, GITHUB_STEP_SUMMARY: summaryPath },
  })

  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, await buildQualitySummary(directory))
  assert.equal(await readFile(summaryPath, 'utf8'), `Previous step\n${result.stdout}`)
})

await test('failed collection with no discovered tests remains a failed result', async (context) => {
  const directory = await reportDirectory(context)
  await writeReports(directory, {
    ...passedTests,
    numTotalTests: 0,
    numPassedTests: 0,
    numPendingTests: 0,
    numTodoTests: 0,
    success: false,
  })

  const summary = await buildQualitySummary(directory)

  assert.match(summary, /Unit test result: \*\*failed\*\*/)
  assert.doesNotMatch(summary, /\*\*no tests\*\*|\*\*passed\*\*/)
})

await test('importing without an entry path neither prints nor appends a report', async (context) => {
  const directory = await reportDirectory(context)
  const summaryPath = join(directory, 'step-summary.md')
  await writeReports(directory)
  await writeFile(summaryPath, 'Previous step\n')
  const moduleURL = new URL('./quality-report.mjs', import.meta.url).href

  const result = spawnSync(
    process.execPath,
    ['--input-type=module', '--eval', `await import(${JSON.stringify(moduleURL)})`],
    {
      cwd: directory,
      encoding: 'utf8',
      env: { ...process.env, GITHUB_STEP_SUMMARY: summaryPath },
    },
  )

  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, '')
  assert.equal(await readFile(summaryPath, 'utf8'), 'Previous step\n')
})
