import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { test } from 'node:test'

import { CELLS, classifyCell, originalCase, sourceSnapshot, summarize } from './protocol.mjs'
import provenance from './provenance.json' with { type: 'json' }

/** @param {Parameters<typeof classifyCell>[0]} cell */
function fixture(cell) {
  const paths = provenance.originalImages.map(
    (image, index) => `/media/media_checks/post-${index}${image.suffix}`,
  )
  const delivery = {
    variant: cell.variant,
    scenario: 'slow-media',
    repeat: cell.order,
    captureStartedAt: 100,
    releasedAt: 1250,
    releaseReason: 'capture-finished-or-error',
    requests: paths.map((path) => ({
      path,
      interceptedAt: 800,
      continuedAt: cell.variant === 'normal' ? 800.1 : 1251,
    })),
    completion: {
      timeOrigin: 10000,
      decoded: paths.map((path) => ({ path, status: 'decoded', complete: true, width: 1400 })),
      resources: paths.map((path) => ({
        path,
        decodedBodySize: 4532573,
        responseEnd: cell.variant === 'normal' ? 900 : 1300,
      })),
    },
  }
  const frames = [750, 1042, 1163].map((time, index) => ({
    time,
    panes: [
      { tab: 'media', visible: true, opacity: index === 2 ? 1 : 0.999, x: index === 2 ? 0 : 0.001 },
    ],
  }))
  const metadata = {
    browser: { name: 'chromium', version: '153.0.8010.12' },
    graphics: { status: 'available', sessionDetached: true },
  }
  const worker = { cell, workerPid: 1000 + cell.order, workerIndex: 0 }
  const images = {
    variant: cell.variant,
    scenario: 'slow-media',
    repeat: cell.order,
    targets: structuredClone(provenance.originalImages),
  }
  return {
    delivery,
    frames,
    metadata,
    worker,
    images,
    report(status = 'failed', retry = 0) {
      const bodies = {
        'diagnostic-cell.json': worker,
        'image-pair-manifest.json': images,
        'image-delivery.json': delivery,
        'slow-tab-frames.json': frames,
        'slow-tab-performance.json': {
          timeOrigin: 10000,
          ended: 1200,
          samplesDropped: 0,
          resourcesDropped: 0,
          observerErrors: [],
          observerEntriesDropped: [],
        },
      }
      const result = {
        status,
        retry,
        attachments: Object.entries(bodies).map(([name, body]) => ({
          name,
          contentType: 'application/json',
          body: Buffer.from(JSON.stringify(body)).toString('base64'),
        })),
      }
      return {
        errors: [],
        suites: [{ specs: [{ title: provenance.caseTitle, tests: [{ results: [result] }] }] }],
      }
    },
  }
}

await test('a failed original assertion stays a valid failed observation and all four cells remain present', () => {
  const outcomes = CELLS.map((cell) => {
    const sample = fixture(cell)
    return classifyCell(
      cell,
      sample.report(cell.variant === 'normal' ? 'failed' : 'passed'),
      sample.metadata,
    )
  })
  assert.deepEqual(
    outcomes.map((outcome) => outcome.cell.id),
    ['01-normal', '02-held', '03-held', '04-normal'],
  )
  assert.ok(outcomes.every((outcome) => outcome.validity === 'valid'))
  assert.deepEqual(
    outcomes.map((outcome) => outcome.result),
    ['failed', 'passed', 'passed', 'failed'],
  )
  assert.equal(outcomes[0]?.settleMs, 413)
})

await test('watchdog release and responses delivered before capture ends invalidate held cells', () => {
  const cell = CELLS[1]
  assert.ok(cell)
  const sample = fixture(cell)
  sample.delivery.releaseReason = 'watchdog'
  const resource = sample.delivery.completion.resources[0]
  assert.ok(resource)
  resource.responseEnd = 1100
  const outcome = classifyCell(cell, sample.report(), sample.metadata)
  assert.equal(outcome.validity, 'invalid')
  assert.ok(outcome.reasons.includes('watchdog-or-missing-release'))
  assert.ok(outcome.reasons.includes('missing-resources-or-held-response-before-capture-end'))
})

await test('duplicate target suffixes, incorrect fixture bytes and failed decode are invalid', () => {
  const cell = CELLS[0]
  assert.ok(cell)
  const sample = fixture(cell)
  const request = sample.delivery.requests[1]
  const target = sample.images.targets[0]
  const decoded = sample.delivery.completion.decoded[0]
  assert.ok(request && target && decoded)
  request.path = `/media/media_checks/other${target.suffix}`
  target.sha256 = 'unexpected'
  decoded.status = 'error'
  const outcome = classifyCell(cell, sample.report(), sample.metadata)
  assert.equal(outcome.validity, 'invalid')
  assert.ok(outcome.reasons.includes('invalid-request-count-or-release-order'))
  assert.ok(outcome.reasons.includes('original-image-hash-or-cell-mismatch'))
  assert.ok(outcome.reasons.includes('original-images-did-not-decode'))
})

await test('missing reports, retried cases and missing browser metadata cannot become valid observations', () => {
  const cell = CELLS[0]
  assert.ok(cell)
  assert.equal(classifyCell(cell, null, null).validity, 'invalid')
  const sample = fixture(cell)
  const outcome = classifyCell(cell, sample.report('passed', 1), null)
  assert.equal(outcome.validity, 'invalid')
  assert.ok(outcome.reasons.includes('retry-or-incomplete-case'))
  assert.ok(outcome.reasons.includes('missing-or-incomplete-browser-metadata'))
})

await test('the diagnostic executes the complete original slow Media case byte for byte', async () => {
  const original = await readFile(new URL('../../e2e/media-tabs.spec.ts', import.meta.url), 'utf8')
  const copied = await readFile(new URL('./slow-media.spec.ts', import.meta.url), 'utf8')
  assert.equal(originalCase(copied), originalCase(original))
})

await test('aggregation preserves later cells after a failed assertion and a corrupt report', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'boosty-diagnostic-unit-'))
  try {
    const snapshot = await sourceSnapshot()
    for (const cell of CELLS) {
      const sample = fixture(cell)
      const cellDirectory = path.join(directory, cell.id)
      await mkdir(path.join(cellDirectory, 'artifacts'), { recursive: true })
      await writeFile(path.join(cellDirectory, 'invariants-before.json'), JSON.stringify(snapshot))
      await writeFile(
        path.join(cellDirectory, 'artifacts/browser-chromium-0.json'),
        JSON.stringify(sample.metadata),
      )
      await writeFile(
        path.join(cellDirectory, 'results.json'),
        cell.order === 3
          ? '{invalid'
          : JSON.stringify(sample.report(cell.order === 1 ? 'failed' : 'passed')),
      )
    }
    const summary = await summarize(directory)
    assert.equal(summary.valid, false)
    assert.equal(summary.originalAssertionsPassed, false)
    assert.equal(summary.productAcceptance, false)
    assert.deepEqual(
      summary.outcomes.map((outcome) => outcome.result),
      ['failed', 'passed', 'missing', 'passed'],
    )
    assert.equal(summary.outcomes[2]?.validity, 'invalid')
    const saved = /** @type {unknown} */ (
      JSON.parse(await readFile(path.join(directory, 'summary.json'), 'utf8'))
    )
    assert.deepEqual(saved, summary)
    const last = CELLS[3]
    assert.ok(last)
    assert.equal(
      await readFile(path.join(directory, '04-normal/raw/slow-tab-frames.json'), 'utf8'),
      JSON.stringify(fixture(last).frames, null, 2) + '\n',
    )
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
