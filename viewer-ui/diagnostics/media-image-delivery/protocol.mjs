import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import provenance from './provenance.json' with { type: 'json' }

/** @typedef {{id: string, order: number, variant: 'normal' | 'delayed'}} Cell */
/** @typedef {{cell: Cell, validity: 'valid' | 'invalid', reasons: string[], result: string, workerPid: number | null, settleMs: number | null}} Outcome */
/** @typedef {{title: unknown, results: unknown[]}} ReportCase */

/** @type {readonly Cell[]} */
export const CELLS = [
  { id: '01-normal', order: 1, variant: 'normal' },
  { id: '02-held', order: 2, variant: 'delayed' },
  { id: '03-held', order: 3, variant: 'delayed' },
  { id: '04-normal', order: 4, variant: 'normal' },
]
const repository = fileURLToPath(new URL('../../../', import.meta.url))
export const REPORT_ROOT = fileURLToPath(
  new URL('../../test-results/media-image-delivery/', import.meta.url),
)
const ATTACHMENTS = [
  'diagnostic-cell.json',
  'image-pair-manifest.json',
  'image-delivery.json',
  'slow-tab-frames.json',
  'slow-tab-performance.json',
]

export function selectedCell() {
  const cell = CELLS.find((item) => item.id === process.env.BOOSTY_MEDIA_CELL)
  if (!cell) throw new Error('BOOSTY_MEDIA_CELL must select one of the four declared cells')
  return cell
}

/** @param {unknown} value @returns {Record<string, unknown>} */
function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? /** @type {Record<string, unknown>} */ (value)
    : {}
}

/** @param {unknown} value @returns {unknown[]} */
function array(value) {
  return Array.isArray(value) ? value : []
}

/** @param {unknown} value @returns {value is number} */
function finite(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

/** @param {string} filename @returns {Promise<unknown>} */
async function json(filename) {
  try {
    return /** @type {unknown} */ (JSON.parse(await readFile(filename, 'utf8')))
  } catch {
    return null
  }
}

/** @param {string} filename @param {unknown} value */
async function save(filename, value) {
  await mkdir(path.dirname(filename), { recursive: true })
  await writeFile(filename, JSON.stringify(value, null, 2) + '\n')
}

/** @param {string | Buffer} body */
function hash(body) {
  return createHash('sha256').update(body).digest('hex')
}

/** @param {string} source */
export function originalCase(source) {
  const start = source.indexOf(`test('${provenance.caseTitle}'`)
  if (start < 0) throw new Error('Original slow Media case was not found')
  const next = source.indexOf("\ntest('", start + 1)
  return source.slice(start, next < 0 ? undefined : next)
}

export async function sourceSnapshot() {
  /** @type {Record<string, {expected: string, actual: string | null, matches: boolean}>} */
  const files = {}
  for (const [name, expected] of Object.entries(provenance.files)) {
    const actual = await readFile(path.join(repository, name)).then(hash, () => null)
    files[name] = { expected, actual, matches: actual === expected }
  }
  let caseMatches = false
  try {
    const source = originalCase(
      await readFile(path.join(repository, 'viewer-ui/e2e/media-tabs.spec.ts'), 'utf8'),
    )
    const copied = originalCase(
      await readFile(new URL('./slow-media.spec.ts', import.meta.url), 'utf8'),
    )
    caseMatches = source === copied && hash(source) === provenance.caseSha256
  } catch {
    caseMatches = false
  }
  return {
    sourceHead: provenance.sourceHead,
    files,
    caseMatches,
    valid: caseMatches && Object.values(files).every((file) => file.matches),
  }
}

/** @param {unknown} suite @returns {ReportCase[]} */
function suiteCases(suite) {
  const record = object(suite)
  const own = array(record.specs).flatMap((spec) =>
    array(object(spec).tests).map((test) => ({
      title: object(spec).title,
      results: array(object(test).results),
    })),
  )
  return [...own, ...array(record.suites).flatMap(suiteCases)]
}

/** @param {unknown} report */
export function reportCases(report) {
  return array(object(report).suites).flatMap(suiteCases)
}

/** @param {unknown} result @param {string} name @returns {unknown} */
export function attachment(result, name) {
  const item = array(object(result).attachments)
    .map(object)
    .find((entry) => entry.name === name)
  if (typeof item?.body !== 'string') return null
  try {
    return /** @type {unknown} */ (JSON.parse(Buffer.from(item.body, 'base64').toString('utf8')))
  } catch {
    return null
  }
}

/** @param {unknown} pathname */
function targetPath(pathname) {
  return (
    typeof pathname === 'string' &&
    pathname.startsWith('/media/media_checks/') &&
    provenance.originalImages.some((image) => pathname.endsWith(image.suffix))
  )
}

/** @param {unknown[]} records */
function fiveTargets(records) {
  return (
    records.length === 5 &&
    new Set(records.map((record) => object(record).path)).size === 5 &&
    records.every((record) => targetPath(object(record).path)) &&
    provenance.originalImages.every(
      (image) =>
        records.filter((record) => String(object(record).path).endsWith(image.suffix)).length === 1,
    )
  )
}

/** @param {Cell} cell @param {unknown} report @param {unknown} metadata @returns {Outcome} */
export function classifyCell(cell, report, metadata) {
  /** @type {Outcome} */
  const outcome = {
    cell,
    validity: 'invalid',
    reasons: [],
    result: 'missing',
    workerPid: null,
    settleMs: null,
  }
  const cases = reportCases(report)
  const test = cases[0]
  if (cases.length !== 1 || test?.title !== provenance.caseTitle || test.results.length !== 1) {
    outcome.reasons.push('expected-one-original-case-and-one-attempt')
    return outcome
  }
  const result = object(test.results[0])
  outcome.result = typeof result.status === 'string' ? result.status : 'missing'
  if (result.retry !== 0 || !['passed', 'failed'].includes(outcome.result))
    outcome.reasons.push('retry-or-incomplete-case')
  if (array(object(report).errors).length) outcome.reasons.push('runner-errors')
  const worker = object(attachment(result, 'diagnostic-cell.json'))
  if (
    JSON.stringify(worker.cell) !== JSON.stringify(cell) ||
    worker.workerIndex !== 0 ||
    !finite(worker.workerPid)
  )
    outcome.reasons.push('missing-or-mismatched-worker-identity')
  else outcome.workerPid = worker.workerPid
  const graphics = object(object(metadata).graphics)
  if (
    object(object(metadata).browser).name !== 'chromium' ||
    object(object(metadata).browser).version !== '153.0.8010.12' ||
    graphics.status !== 'available' ||
    graphics.sessionDetached !== true
  )
    outcome.reasons.push('missing-or-incomplete-browser-metadata')
  const manifest = object(attachment(result, 'image-pair-manifest.json'))
  if (
    manifest.variant !== cell.variant ||
    manifest.scenario !== 'slow-media' ||
    manifest.repeat !== cell.order ||
    JSON.stringify(manifest.targets) !== JSON.stringify(provenance.originalImages)
  )
    outcome.reasons.push('original-image-hash-or-cell-mismatch')
  const delivery = object(attachment(result, 'image-delivery.json'))
  const completion = object(delivery.completion)
  const performance = object(attachment(result, 'slow-tab-performance.json'))
  const requests = array(delivery.requests).map(object)
  const decoded = array(completion.decoded).map(object)
  const resources = array(completion.resources).map(object)
  if (
    delivery.variant !== cell.variant ||
    delivery.scenario !== 'slow-media' ||
    delivery.repeat !== cell.order
  )
    outcome.reasons.push('delivery-cell-mismatch')
  if (delivery.releaseReason !== 'capture-finished-or-error')
    outcome.reasons.push('watchdog-or-missing-release')
  const { captureStartedAt, releasedAt } = delivery
  if (
    !finite(captureStartedAt) ||
    !finite(releasedAt) ||
    releasedAt <= captureStartedAt ||
    !fiveTargets(requests) ||
    !requests.every(
      (request) =>
        finite(request.interceptedAt) &&
        finite(request.continuedAt) &&
        request.interceptedAt >= captureStartedAt &&
        request.interceptedAt < releasedAt &&
        request.continuedAt >= request.interceptedAt &&
        (cell.variant === 'delayed'
          ? request.continuedAt >= releasedAt
          : request.continuedAt < releasedAt),
    )
  )
    outcome.reasons.push('invalid-request-count-or-release-order')
  if (
    !fiveTargets(decoded) ||
    !decoded.every(
      (image) =>
        image.status === 'decoded' &&
        image.complete === true &&
        finite(image.width) &&
        image.width > 0,
    )
  )
    outcome.reasons.push('original-images-did-not-decode')
  const ended = performance.ended
  if (
    !fiveTargets(resources) ||
    !resources.every((resource) =>
      provenance.originalImages.some(
        (image) =>
          typeof resource.path === 'string' &&
          resource.path.endsWith(image.suffix) &&
          resource.decodedBodySize === image.bytes,
      ),
    ) ||
    !finite(ended) ||
    (cell.variant === 'delayed' &&
      !resources.every((resource) => finite(resource.responseEnd) && resource.responseEnd > ended))
  )
    outcome.reasons.push('missing-resources-or-held-response-before-capture-end')
  if (
    performance.timeOrigin !== completion.timeOrigin ||
    performance.samplesDropped !== 0 ||
    performance.resourcesDropped !== 0 ||
    array(performance.observerErrors).length ||
    array(performance.observerEntriesDropped).some((entry) => object(entry).count !== 0)
  )
    outcome.reasons.push('incomplete-performance-evidence')
  const frames = array(attachment(result, 'slow-tab-frames.json')).map(object)
  const incoming = frames.flatMap((frame) =>
    array(frame.panes)
      .map(object)
      .filter((pane) => pane.tab === 'media' && pane.visible === true)
      .map((pane) => ({ opacity: pane.opacity, x: pane.x, time: frame.time })),
  )
  const first = incoming[0]
  const settled = incoming.find(
    (pane) => pane.opacity === 1 && finite(pane.x) && Math.abs(pane.x) < 0.1,
  )
  if (finite(first?.time) && finite(settled?.time)) outcome.settleMs = settled.time - first.time
  else outcome.reasons.push('missing-original-frame-evidence')
  outcome.validity = outcome.reasons.length ? 'invalid' : 'valid'
  return outcome
}

/** @param {string} directory */
export async function summarize(directory = REPORT_ROOT) {
  const after = await sourceSnapshot()
  await save(path.join(directory, 'invariants-after.json'), after)
  const outcomes = []
  const metadataRecords = []
  for (const cell of CELLS) {
    const cellDirectory = path.join(directory, cell.id)
    const report = await json(path.join(cellDirectory, 'results.json'))
    const metadata = await json(path.join(cellDirectory, 'artifacts/browser-chromium-0.json'))
    const before = object(await json(path.join(cellDirectory, 'invariants-before.json')))
    const outcome = classifyCell(cell, report, metadata)
    if (
      before.valid !== true ||
      !after.valid ||
      JSON.stringify(before.files) !== JSON.stringify(after.files)
    ) {
      outcome.validity = 'invalid'
      outcome.reasons.push('source-or-asset-provenance-mismatch')
    }
    const result = reportCases(report)[0]?.results[0]
    for (const name of ATTACHMENTS) {
      const payload = attachment(result, name)
      if (payload !== null) await save(path.join(cellDirectory, 'raw', name), payload)
    }
    outcomes.push(outcome)
    metadataRecords.push(JSON.stringify(metadata))
  }
  const pids = outcomes.map((outcome) => outcome.workerPid)
  const distinctWorkers = pids.every((pid) => pid !== null) && new Set(pids).size === 4
  const sameBrowserRuntime = new Set(metadataRecords).size === 1 && metadataRecords[0] !== 'null'
  const valid =
    after.valid &&
    distinctWorkers &&
    sameBrowserRuntime &&
    outcomes.every((outcome) => outcome.validity === 'valid')
  const originalAssertionsPassed = outcomes.every((outcome) => outcome.result === 'passed')
  const summary = {
    diagnosticOnly: true,
    productAcceptance: false,
    valid,
    distinctWorkers,
    sameBrowserRuntime,
    originalAssertionsPassed,
    outcomes,
  }
  await save(path.join(directory, 'summary.json'), summary)
  return summary
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] === 'verify') {
    const snapshot = await sourceSnapshot()
    await save(path.join(REPORT_ROOT, selectedCell().id, 'invariants-before.json'), snapshot)
    if (!snapshot.valid) process.exitCode = 2
  } else if (process.argv[2] === 'summarize') {
    const summary = await summarize()
    console.log(JSON.stringify(summary, null, 2))
    if (!summary.valid || !summary.originalAssertionsPassed) process.exitCode = 1
  } else throw new Error('Expected verify or summarize')
}
