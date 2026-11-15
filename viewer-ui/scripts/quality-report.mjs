import { appendFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/** @typedef {{ total: number, covered: number, pct: number }} CoverageMetric */
/** @typedef {{ total: number, passed: number, failed: number, skipped: number, todo: number, success: boolean, durationMs: number | null }} TestSummary */
/** @typedef {{ value: unknown, problem: null } | { value: null, problem: string }} Report */

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** @param {unknown} value @returns {value is number} */
function isCount(value) {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

/** @param {unknown} value @returns {value is number} */
function isTime(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

/** @param {string} path @returns {Promise<Report>} */
async function readReport(path) {
  try {
    /** @type {unknown} */
    const value = JSON.parse(await readFile(path, 'utf8'))
    return { value, problem: null }
  } catch (error) {
    if (isRecord(error) && error.code === 'ENOENT')
      return { value: null, problem: 'missing report' }
    if (error instanceof SyntaxError) return { value: null, problem: 'invalid JSON' }
    return { value: null, problem: 'report could not be read' }
  }
}

/** @param {unknown} value @returns {CoverageMetric | null} */
function coverageMetric(value) {
  if (!isRecord(value)) return null
  const { total, covered, pct } = value
  if (!isCount(total) || !isCount(covered) || covered > total) return null
  if (typeof pct !== 'number' || !Number.isFinite(pct) || pct < 0 || pct > 100) return null
  return { total, covered, pct }
}

/** @param {unknown} value @returns {TestSummary | null} */
function testSummary(value) {
  if (!isRecord(value)) return null
  const {
    numTotalTests: total,
    numPassedTests: passed,
    numFailedTests: failed,
    numPendingTests: skipped,
    numTodoTests: todo,
    success,
    startTime,
    testResults,
  } = value
  if (
    !isCount(total) ||
    !isCount(passed) ||
    !isCount(failed) ||
    !isCount(skipped) ||
    !isCount(todo)
  )
    return null
  if (total !== passed + failed + skipped + todo || typeof success !== 'boolean') return null
  if (!isTime(startTime) || !Array.isArray(testResults)) return null
  let endTime = startTime
  for (const result of testResults) {
    if (!isRecord(result) || !isTime(result.endTime) || result.endTime < startTime) return null
    endTime = Math.max(endTime, result.endTime)
  }
  return {
    total,
    passed,
    failed,
    skipped,
    todo,
    success,
    durationMs: testResults.length ? endTime - startTime : null,
  }
}

/** @param {Report} report @returns {string[]} */
function testLines(report) {
  const tests = testSummary(report.value)
  if (!tests) return [`Unit tests: unavailable (${report.problem ?? 'invalid report fields'}).`]
  let result = 'failed'
  if (tests.success && tests.failed === 0) {
    result = 'passed'
    if (tests.total === 0) result = 'no tests'
  }
  const duration =
    tests.durationMs === null ? 'unavailable' : `${(tests.durationMs / 1000).toFixed(2)} s`
  return [
    `Unit test result: **${result}**. Test duration: ${duration}.`,
    '',
    '| Total | Passed | Failed | Skipped | Todo |',
    '| ---: | ---: | ---: | ---: | ---: |',
    `| ${tests.total} | ${tests.passed} | ${tests.failed} | ${tests.skipped} | ${tests.todo} |`,
  ]
}

/** @param {Report} report @returns {string[]} */
function coverageLines(report) {
  if (!isRecord(report.value) || !isRecord(report.value.total)) {
    return [`Coverage: unavailable (${report.problem ?? 'invalid report fields'}).`]
  }
  const metrics = ['statements', 'branches', 'functions', 'lines']
  const lines = ['| Coverage | Covered | Total | Percent |', '| --- | ---: | ---: | ---: |']
  for (const name of metrics) {
    const metric = coverageMetric(report.value.total[name])
    lines.push(
      metric
        ? `| ${name} | ${metric.covered} | ${metric.total} | ${metric.pct.toFixed(2)}% |`
        : `| ${name} | unavailable | unavailable | unavailable |`,
    )
  }
  return lines
}

/** @param {string} directory @returns {Promise<string>} */
export async function buildQualitySummary(directory) {
  const [tests, coverage] = await Promise.all([
    readReport(join(directory, 'reports/unit-tests.json')),
    readReport(join(directory, 'coverage/coverage-summary.json')),
  ])
  return ['## Frontend quality', '', ...testLines(tests), '', ...coverageLines(coverage), ''].join(
    '\n',
  )
}

const entryPath = process.argv[1]
if (entryPath && import.meta.url === pathToFileURL(entryPath).href) {
  const summary = await buildQualitySummary(process.cwd())
  process.stdout.write(summary)
  if (process.env.GITHUB_STEP_SUMMARY)
    await appendFile(process.env.GITHUB_STEP_SUMMARY, summary, 'utf8')
}
