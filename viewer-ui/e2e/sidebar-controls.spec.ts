import type { Page, TestInfo } from '@playwright/test'

import { expect, openPost, pane, POSTS, sidebar, test } from './post-fixtures'
import { requireFixture } from './required-fixture'
import {
  captureReaderInput,
  type ReaderInputAttempt,
  type ReaderInputSnapshot,
} from './sidebar-native-input'
import {
  blurControl,
  content,
  dragTo,
  expectWidth,
  frames,
  layout,
  physicalBracket,
  savedPreference,
  seedPreference,
  separator,
  toggle,
  width,
  widthFrames,
  WIDTH,
  type WidthFrame,
} from './sidebar-fixtures'

const MAX_INPUT_ATTEMPTS = 3

test('drag is immediate, keyboard changes persist, and the resize hit area resets', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader)
  for (const target of [260, 640, 450]) {
    await dragTo(page, target)
    await expect(layout(page)).not.toHaveAttribute('data-animating')
    expect(await savedPreference(page)).toEqual({ width: target, collapsed: false })
  }
  await separator(page).focus()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => width(page)).toBeGreaterThan(450)
  await expect(layout(page)).not.toHaveAttribute('data-animating')
  const chosen = await width(page)
  expect(Math.abs((await savedPreference(page)).width - chosen)).toBeLessThanOrEqual(0.5)
  await page.reload()
  await expectWidth(page, chosen)
  const edge = requireFixture(await separator(page).boundingBox())
  await page.mouse.dblclick(edge.x + edge.width / 2 + 5, edge.y + 100)
  await expectWidth(page, 360)
  expect(await savedPreference(page)).toEqual({ width: 360, collapsed: false })
})

test('toggle and reset glide through intermediate widths while reduced motion is immediate', async ({
  page,
  corpus,
}, info) => {
  await seedPreference(page, JSON.stringify({ width: 500, collapsed: false }))
  await openPost(page, corpus, POSTS.reader)
  await expectWidth(page, 500)
  const collapsed = await recordWidthFrames(page, 'toggle', info, 'collapse')
  expect(collapsed.at(-1)?.width).toBeLessThanOrEqual(0.5)
  expect(
    new Set(
      collapsed
        .filter((sample) => sample.width > 1 && sample.width < 499)
        .map((sample) => Math.round(sample.width)),
    ).size,
  ).toBeGreaterThanOrEqual(3)
  const expanded = await recordWidthFrames(page, 'toggle', info, 'expand')
  expect(Math.abs(requireFixture(expanded.at(-1)).width - 500)).toBeLessThanOrEqual(0.5)
  expect(expanded.some((sample) => sample.width > 1 && sample.width < 499)).toBe(true)
  const reset = await recordWidthFrames(page, 'reset', info, 'reset')
  expect(reset.some((sample) => sample.width > 361 && sample.width < 499)).toBe(true)
  await expectWidth(page, 360)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const immediate = await recordWidthFrames(page, 'toggle', info, 'reduced-motion')
  expect(immediate.slice(1).every((sample) => sample.width <= 0.5)).toBe(true)
  await expect(layout(page)).not.toHaveAttribute('data-animating')
})

async function recordWidthFrames(
  page: Page,
  action: 'toggle' | 'reset',
  info: TestInfo,
  name: string,
): Promise<WidthFrame[]> {
  const readings = await widthFrames(page, action)
  await info.attach(`sidebar-${name}-frames.json`, {
    body: JSON.stringify(readings),
    contentType: 'application/json',
  })
  expect(
    readings.every((sample) => {
      const minimum = sample.animating ? WIDTH.min : 0
      return Math.abs(sample.contentWidth - Math.max(minimum, sample.width)) <= 0.5
    }),
    'Sidebar contents keep a usable width throughout the glide',
  ).toBe(true)
  expect(
    readings.every((sample) => Math.abs(sample.contentHeight - sample.panelHeight) <= 0.5),
    'Clipped contents do not introduce a horizontal scrollbar',
  ).toBe(true)
  return readings
}

test('reduced-motion button, bracket, Enter and arrow changes preserve the reading offset', async ({
  page,
  corpus,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await seedPreference(page, JSON.stringify({ width: 500, collapsed: false }))
  await openPost(page, corpus, POSTS.reader)
  await expectWidth(page, 500)
  await pane(page).evaluate((element) => {
    element.scrollTop = 120
  })
  await frames(page, 3)
  const expectReadingOffset = async (expectedWidth: number): Promise<void> => {
    await expectWidth(page, expectedWidth)
    await expect(layout(page)).not.toHaveAttribute('data-animating')
    await frames(page, 3)
    expect(await pane(page).evaluate((element) => element.scrollTop)).toBe(120)
  }
  await toggle(page).click()
  await expectReadingOffset(0)
  await toggle(page).click()
  await expectReadingOffset(500)
  await blurControl(page)
  await page.keyboard.press('[')
  await expectReadingOffset(0)
  await page.keyboard.press('[')
  await expectReadingOffset(500)
  await separator(page).focus()
  await page.keyboard.press('Enter')
  await expectReadingOffset(0)
  await page.keyboard.press('Enter')
  await expectReadingOffset(500)
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => width(page)).toBeGreaterThan(500)
  await expectReadingOffset(await width(page))
})

for (const input of ['wheel', 'keyboard'] as const) {
  test(`native ${input} input during a sidebar glide keeps the reader's new scroll position`, async ({
    page,
    corpus,
  }, info) => {
    await seedPreference(page, JSON.stringify({ width: 500, collapsed: false }))
    await openPost(page, corpus, POSTS.reader)
    const attempts: ReaderInputAttempt[] = []
    let selected: ReaderInputSnapshot | null = null
    for (let number = 1; number <= MAX_INPUT_ATTEMPTS; number++) {
      if (number > 1) {
        await expectWidth(page, 0)
        await expect(layout(page)).not.toHaveAttribute('data-animating')
        await toggle(page).click()
      }
      await expectWidth(page, 500)
      await expect(layout(page)).not.toHaveAttribute('data-animating')
      await pane(page).getByRole('link', { name: 'Boosty', exact: true }).focus()
      const bounds = requireFixture(await pane(page).boundingBox())
      await page.mouse.move(bounds.x + bounds.width - 24, bounds.y + bounds.height / 2)
      await pane(page).evaluate((element) => {
        element.scrollTop = 120
      })
      await frames(page, 3)
      const attempt = await captureReaderInput(page, input, 500)
      attempts.push(attempt)
      await info.attach(`sidebar-native-reader-input-attempt-${number}.json`, {
        body: JSON.stringify({ input, number, ...attempt }),
        contentType: 'application/json',
      })
      expect(attempt.error).toBeNull()
      const snapshot = attempt.captured
      if (snapshot) {
        expect(snapshot.trusted).toBe(true)
        if (snapshot.animating && snapshot.sidebarWidth > 0 && snapshot.sidebarWidth < 500) {
          selected = snapshot
          break
        }
      }
    }
    await info.attach('sidebar-native-reader-input.json', {
      body: JSON.stringify({ input, captured: selected, attempts }),
      contentType: 'application/json',
    })
    expect(
      selected,
      'Native input must arrive during a sidebar glide within three attempts',
    ).not.toBeNull()
    const captured = requireFixture(selected)
    expect(captured.trusted).toBe(true)
    expect(captured.animating).toBe(true)
    expect(captured.sidebarWidth).toBeGreaterThan(0)
    expect(captured.sidebarWidth).toBeLessThan(500)
    await expectWidth(page, 0)
    await expect(layout(page)).not.toHaveAttribute('data-animating')
    await expect
      .poll(() => pane(page).evaluate((element) => element.scrollTop))
      .toBeGreaterThan(220)
    await frames(page, 30)
    expect(await pane(page).evaluate((element) => element.scrollTop)).toBeGreaterThan(220)
  })
}

test('physical bracket transfers focus out of collapsed content and slash expands into search', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader)
  const search = sidebar(page).getByRole('textbox', { name: 'Search posts' })
  await expect(toggle(page)).toHaveAttribute('aria-keyshortcuts', '[')
  await expect(toggle(page)).toHaveAccessibleName('Hide sidebar')
  await sidebar(page).locator('[data-post-id]').first().focus()
  await physicalBracket(page)
  await expectWidth(page, 0)
  await expect(content(page)).toHaveAttribute('inert', '')
  await expect(toggle(page)).toBeFocused()
  await physicalBracket(page, '[')
  await expectWidth(page, 360)
  await search.fill('needle')
  await toggle(page).click()
  await expectWidth(page, 0)
  await page.keyboard.press('/')
  await expect(search).toBeFocused()
  await expectWidth(page, 360)
  expect(
    await search.evaluate((element: HTMLInputElement) => ({
      start: element.selectionStart,
      end: element.selectionEnd,
    })),
  ).toEqual({ start: 0, end: 6 })
  await physicalBracket(page)
  await expectWidth(page, 360)
})

test('modifier, composition, editor and native-media keys do not toggle the sidebar', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader)
  const search = sidebar(page).getByRole('textbox', { name: 'Search posts' })
  for (const control of [
    search,
    sidebar(page).getByRole('combobox', { name: 'Tag' }),
    pane(page).locator('audio').first(),
  ]) {
    await control.focus()
    await physicalBracket(page)
    await expectWidth(page, 360)
  }
  await pane(page).evaluate((element) => {
    const editor = document.createElement('div')
    editor.contentEditable = 'true'
    editor.setAttribute('aria-label', 'Sidebar editor guard')
    element.prepend(editor)
    editor.focus()
  })
  await physicalBracket(page)
  await expectWidth(page, 360)
  await page.getByLabel('Sidebar editor guard').evaluate((element) => element.remove())
  await blurControl(page)
  for (const options of [
    { ctrlKey: true },
    { metaKey: true },
    { altKey: true },
    { shiftKey: true },
    { isComposing: true },
    { repeat: true },
  ]) {
    await page.evaluate(
      (options) =>
        document.body.dispatchEvent(
          new KeyboardEvent('keydown', {
            code: 'BracketLeft',
            key: '[',
            bubbles: true,
            cancelable: true,
            ...options,
          }),
        ),
      options,
    )
    await expectWidth(page, 360)
  }
  await physicalBracket(page)
  await expectWidth(page, 0)
})

test('a bulk dialog owns shortcuts and a double-click cannot reset through its portal', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader)
  await dragTo(page, 500)
  await sidebar(page).getByRole('button', { name: 'Mark posts', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Mark all as seen', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await physicalBracket(page)
  await page.keyboard.press('/')
  expect(await content(page).getAttribute('inert')).toBeNull()
  const edge = requireFixture(
    await page.locator('[role="separator"][aria-label="Sidebar width"]').boundingBox(),
  )
  await dialog.dispatchEvent('dblclick', {
    clientX: edge.x + edge.width / 2,
    clientY: edge.y + 100,
  })
  await frames(page, 3)
  await expectWidth(page, 500)
  expect(await savedPreference(page)).toEqual({ width: 500, collapsed: false })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('tooltips close when their header or narrow kind control becomes unavailable', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader)
  await toggle(page).focus()
  await expect(page.getByRole('tooltip')).toContainText('Hide sidebar')
  await page.setViewportSize({ width: 767, height: 1000 })
  await expect(toggle(page)).toBeEnabled()
  await expect(toggle(page)).toHaveAccessibleName('Show sidebar')
  await expect(page.getByRole('tooltip')).not.toContainText('Hide sidebar')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await dragTo(page, 260)
  const photos = sidebar(page).getByRole('button', { name: 'Photos', exact: true })
  await blurControl(page)
  await photos.hover()
  await expect(page.getByRole('tooltip')).toContainText('Photos')
  await physicalBracket(page)
  await expectWidth(page, 0)
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  await physicalBracket(page)
  await expectWidth(page, 260)
  await expect(page.getByRole('tooltip')).toHaveCount(0)
})

test('history navigation closes a focused kind tooltip when Posts becomes inactive', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader)
  await dragTo(page, 260)
  await page
    .getByRole('navigation', { name: 'Author', exact: true })
    .getByRole('link', { name: 'Media', exact: true })
    .click()
  await expect(page.getByRole('region', { name: 'Author media' })).toBeVisible()
  await page.goBack()
  await expectWidth(page, 260)
  await sidebar(page).getByRole('button', { name: 'Photos', exact: true }).focus()
  await expect(page.getByRole('tooltip')).toContainText('Photos')
  await page.goForward()
  await expect(page.getByRole('region', { name: 'Author media' })).toBeVisible()
  await expect(page.getByRole('tooltip')).toHaveCount(0)
})
