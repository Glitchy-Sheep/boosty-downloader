import { setTimeout as delay } from 'node:timers/promises'

import { expect, test, AUTHOR, detail, mediaPath, openPost, pane } from '../../e2e/media-fixtures'
import { verifySwitch } from '../../e2e/media-frames'
import { preparePair, recordSwitch } from './harness'
import { selectedCell } from './protocol.mjs'

const cell = selectedCell()

test.use({ trace: 'off' })
test.beforeEach(async ({ page, corpus }, info) => {
  await info.attach('diagnostic-cell.json', {
    body: JSON.stringify({ cell, workerPid: process.pid, workerIndex: info.workerIndex }),
    contentType: 'application/json',
  })
  await preparePair(page, corpus.library, cell.variant, 'slow-media', cell.order, info)
})

test('slow Media moves its pill immediately and disables the outgoing post before the response', async ({
  page,
  corpus,
}, info) => {
  await openPost(page, corpus)
  const marks = await detail(page, corpus)
  let requested = false
  await page.route(`**/api/authors/${AUTHOR}/media*`, async (route) => {
    requested = true
    await delay(650)
    await route.continue()
  })
  const recording = recordSwitch(page, 'media', info, 'slow-tab', { duration: 1100 })
  await expect.poll(() => requested).toBe(true)
  await expect(pane(page, 'posts')).toHaveAttribute('inert', '')
  const text = await pane(page, 'posts').innerText()
  expect(text).toContain('Media post 01')
  await page.keyboard.press('j')
  await page.keyboard.press('s')
  await page.keyboard.press('f')
  await page.keyboard.press('/')
  await page.keyboard.press('[')
  const frames = await recording
  verifySwitch(frames, 'media')
  const settledPill = frames.at(-1)!.pill
  expect(frames.find((frame) => Math.abs(frame.pill - settledPill) < 0.1)!.time).toBeLessThan(400)
  expect(
    frames.find((frame) => frame.panes.some((part) => part.tab === 'media'))!.time,
  ).toBeGreaterThanOrEqual(600)
  expect(new URL(page.url()).pathname).toBe(mediaPath())
  const after = await detail(page, corpus)
  expect({ seen: after.seen, favorite: after.favorite }).toEqual({
    seen: marks.seen,
    favorite: marks.favorite,
  })
  expect(
    await page.evaluate(
      () => document.activeElement?.closest('.author-pane[data-tab="posts"]') !== null,
    ),
  ).toBe(false)
})
