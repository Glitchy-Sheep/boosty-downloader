import type { Locator, Page } from '@playwright/test'

import type { MediaPage } from '../src/lib/api.gen'
import {
  API_PATH,
  capabilities,
  expect,
  itemRow,
  localCapabilities,
  ofType,
  openFiles,
  requireFixture,
  test,
  watchRuntime,
  type RuntimeCheck,
} from './file-actions-fixtures'

async function measurements(name: Locator): Promise<{
  available: number
  natural: number
  stemCut: number
  suffixCut: number
  lines: number
}> {
  return name.evaluate((element) => {
    const box = element.querySelector('span[title]')
    const stem = box?.children[0]
    const suffix = box?.children[1]
    if (!box || !stem || !suffix) throw new Error('Missing inline filename parts')
    const range = document.createRange()
    range.selectNodeContents(stem)
    const naturalStem = range.getBoundingClientRect().width
    range.selectNodeContents(suffix)
    const naturalSuffix = range.getBoundingClientRect()
    return {
      available: box.getBoundingClientRect().width,
      natural: naturalStem + naturalSuffix.width,
      stemCut: naturalStem - stem.getBoundingClientRect().width,
      suffixCut: naturalSuffix.right - box.getBoundingClientRect().right,
      lines: Math.abs(stem.getBoundingClientRect().top - suffix.getBoundingClientRect().top),
    }
  })
}

type FilenameCopy = { selected: string; text: string; handled: boolean }

declare global {
  interface Window {
    filenameCopies?: FilenameCopy[]
  }
}

async function observeFilenameCopies(page: Page): Promise<void> {
  await page.evaluate(() => {
    window.filenameCopies = []
    document.addEventListener('copy', (event) => {
      window.filenameCopies?.push({
        selected: window.getSelection()?.toString() ?? '',
        text: event.clipboardData?.getData('text/plain') ?? '',
        handled: event.defaultPrevented,
      })
    })
  })
}

async function copyFilename(
  page: Page,
  name: Locator,
  expected: string,
  readClipboard: boolean,
  partial = false,
): Promise<void> {
  await name.click()
  const diagnostic = await name.evaluate((element: HTMLElement, isPartial) => {
    const range = document.createRange()
    range.selectNodeContents(element)
    if (isPartial) {
      const box = element.querySelector('span[title]')
      const stem = box?.children[0]?.firstChild
      const suffix = box?.children[1]?.firstChild
      if (!stem?.textContent || !suffix?.textContent) throw new Error('Missing filename text nodes')
      range.setStart(stem, 2)
      range.setEnd(suffix, suffix.textContent.length - 2)
    }
    const selection = window.getSelection()
    if (!selection) throw new Error('The page has no text selection')
    selection.removeAllRanges()
    selection.addRange(range)
    window.filenameCopies = []
    return { selected: selection.toString(), innerText: element.innerText }
  }, partial)
  await page.keyboard.press('ControlOrMeta+C')
  await expect.poll(() => page.evaluate(() => window.filenameCopies?.length)).toBe(1)
  const copied = requireFixture(await page.evaluate(() => window.filenameCopies?.[0]))
  expect(copied.handled ? copied.text : copied.selected, JSON.stringify(diagnostic)).toBe(expected)
  if (readClipboard)
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(expected)
  await page.evaluate(() => window.getSelection()?.removeAllRanges())
}

for (const width of [1280, 1440]) {
  test(`${width}px shows fitting filenames whole and distinct file type icons`, async ({
    page,
    corpus,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    await capabilities(page, localCapabilities(corpus))
    const data = await openFiles(page, corpus)
    const colors = new Map<string, string>()
    for (const type of [
      'pdf',
      'document',
      'book',
      'sheet',
      'slides',
      'image',
      'audio',
      'video',
      'archive',
      'model',
      'code',
      'font',
      'program',
      'script',
      'other',
    ] as const) {
      const item = ofType(data, type)
      const row = await itemRow(page, data, item)
      const filename = requireFixture(item.path.split('/').at(-1))
      expect(await row.locator('.file-name').textContent()).toBe(filename)
      await expect(row.getByRole('img')).toHaveCount(1)
      colors.set(
        type,
        await row.getByRole('img').evaluate((element) => getComputedStyle(element).color),
      )
      const result = await measurements(row.locator('.file-name'))
      if (result.natural <= result.available + 0.01)
        expect(result.stemCut, item.path).toBeLessThanOrEqual(0.01)
      expect(result.suffixCut, item.path).toBeLessThanOrEqual(0.01)
      expect(result.lines, item.path).toBeLessThanOrEqual(0.01)
    }
    expect(colors.get('pdf')).not.toBe(colors.get('archive'))
    expect(new Set(colors.values()).size).toBeGreaterThanOrEqual(9)
    if (width === 1440) {
      await page.locator('[data-media-scroller]').evaluate((element) => {
        element.scrollTop = 0
      })
      await expect(page.locator(`[data-media-id="${ofType(data, 'pdf').id}"]`)).toBeVisible()
      await page.screenshot({ path: test.info().outputPath('files-desktop-dark.png') })
      await page.emulateMedia({ colorScheme: 'light' })
      await page.screenshot({
        path: test.info().outputPath('files-desktop-light.png'),
        animations: 'disabled',
      })
    }
  })
}

test('fractional fit boundaries and CSS zoom never clip a visible suffix', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  const row = await itemRow(page, data, ofType(data, 'document'))
  const name = row.locator('.file-name')
  for (const zoom of [1, 1.1, 1.25, 1.5]) {
    await page.evaluate((value) => {
      document.documentElement.style.zoom = String(value)
    }, zoom)
    await name.evaluate((element: HTMLElement) => {
      element.style.width = '400px'
      element.style.flex = 'none'
    })
    await expect.poll(async () => (await measurements(name)).stemCut).toBeLessThanOrEqual(0.01)
    const natural = (await measurements(name)).natural / zoom
    for (const delta of [-0.49, -0.1, -0.03, -0.01, 0, 0.01, 0.1, 0.49]) {
      await name.evaluate((element: HTMLElement, size) => {
        element.style.width = `${size}px`
      }, natural + delta)
      await expect
        .poll(async () => (await measurements(name)).suffixCut, {
          message: `No fractional suffix clipping at zoom ${zoom}, delta ${delta}`,
        })
        .toBeLessThanOrEqual(0.01)
      const result = await measurements(name)
      if (result.natural <= result.available + 0.01)
        await expect
          .poll(async () => (await measurements(name)).stemCut, {
            message: `Fitting stem at ${JSON.stringify({ zoom, delta, ...result })}`,
          })
          .toBeLessThanOrEqual(0.01)
    }
  }
})

test('browser scale and narrower CSS viewport preserve fitting names', async ({
  browser,
  corpus,
}) => {
  for (const [deviceScaleFactor, width] of [
    [2.2, 1164],
    [2.5, 1024],
    [3, 853],
  ] as const) {
    const context = await browser.newContext({
      viewport: { width, height: 1000 },
      deviceScaleFactor,
    })
    let runtime: RuntimeCheck | undefined
    try {
      const page = await context.newPage()
      runtime = await watchRuntime(page, corpus)
      await capabilities(page, localCapabilities(corpus))
      const data = await openFiles(page, corpus)
      const row = await itemRow(page, data, ofType(data, 'document'))
      await expect
        .poll(async () => (await measurements(row.locator('.file-name'))).stemCut)
        .toBeLessThanOrEqual(0.01)
    } finally {
      await context.close()
      runtime?.assertClean()
    }
  }
})

test('displayed paths preserve spaces, replace controls and keep the longest suffix visible', async ({
  page,
  context,
  browserName,
  corpus,
}) => {
  if (browserName === 'chromium')
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.setViewportSize({ width: 640, height: 1000 })
  await capabilities(page, localCapabilities(corpus))
  const names = [
    'Repeated  spaces, 100%25.txt',
    'Line\nbreak\tand\u0001control.txt',
    `A long name ${'wide stem '.repeat(12)}.settingcontent-ms`,
    `invoice\u202efdp.exe`,
    `A long name ${'wide stem '.repeat(12)}.abcdefghijklmnopqrstuvw`,
    'setup.exe.',
  ]
  await page.route(`**${API_PATH}/media?*`, async (route) => {
    const response = await route.fetch()
    const data = (await response.json()) as MediaPage
    const template = requireFixture(data.items[0])
    const directory = template.path.slice(0, template.path.lastIndexOf('/') + 1)
    await route.fulfill({
      json: {
        ...data,
        items: names.map((name, index) => ({
          ...template,
          id: `display-${index}`,
          path: directory + name,
          file_type: index >= 2 ? 'program' : 'document',
        })),
      },
    })
  })
  await openFiles(page, corpus)
  await observeFilenameCopies(page)
  for (const [index, original] of names.entries()) {
    const row = page.locator(`[data-media-id="display-${index}"]`)
    const name = row.locator('.file-name')
    const cleaned = original
      .replace(/[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g, '')
      .replace(/[\p{Cc}\u2028\u2029]/gu, '\ufffd')
    await expect(name).toHaveText(cleaned, { useInnerText: false })
    expect(await name.textContent()).toBe(cleaned)
    await copyFilename(page, name, cleaned, browserName === 'chromium')
    if (index === 0)
      await copyFilename(page, name, cleaned.slice(2, -2), browserName === 'chromium', true)
    await expect(name.locator('span[title]')).toHaveCSS('white-space', 'pre')
    const result = await measurements(name)
    expect(result.suffixCut, original).toBeLessThanOrEqual(0.01)
    expect(result.lines, original).toBeLessThanOrEqual(0.01)
    if (index === 2 || index === 4) expect(result.stemCut).toBeGreaterThan(0)
    if (index === 3 || index === 5)
      await expect(row.getByText('Program', { exact: true })).toBeVisible()
  }
})
