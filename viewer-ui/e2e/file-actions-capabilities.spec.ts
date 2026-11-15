import { hostname } from 'node:os'

import type { OpenerCapabilities } from '../src/lib/api.gen'
import {
  API_PATH,
  AUTHOR,
  capabilities,
  expect,
  itemRow,
  localCapabilities,
  ofType,
  openFiles,
  openPost,
  remoteCapabilities,
  requireFixture,
  sourcePath,
  test,
} from './file-actions-fixtures'

test('startup waits for capabilities without flashing local or remote View actions', async ({
  page,
  corpus,
}) => {
  let release: (() => void) | undefined
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  let requests = 0
  await page.route('**/api/opener', async (route) => {
    requests += 1
    await pending
    await route.fulfill({ json: localCapabilities(corpus) })
  })
  await page.addInitScript(() => {
    const seen: string[] = []
    Object.defineProperty(window, 'fileActionHistory', { value: seen })
    new MutationObserver(() => {
      for (const element of document.querySelectorAll('[data-action="view"]'))
        seen.push(element.textContent ?? '')
    }).observe(document, { subtree: true, childList: true })
  })
  const data = await openFiles(page, corpus)
  const row = await itemRow(page, data, ofType(data, 'pdf'))
  await expect(row.getByRole('button', { name: 'Open in default app' })).toHaveCount(0)
  await expect(row.getByRole('link', { name: 'View in a new tab' })).toHaveCount(0)
  requireFixture(release)()
  await expect(row.getByRole('button', { name: 'Open in default app' })).toBeVisible()
  expect(
    await page.evaluate(
      () => (window as Window & { fileActionHistory?: string[] }).fileActionHistory,
    ),
  ).toEqual([])
  await page
    .getByRole('navigation', { name: 'Author', exact: true })
    .getByRole('link', { name: 'Posts', exact: true })
    .click()
  await expect(page.locator('.author-pane[data-tab="posts"]')).toBeVisible()
  expect(requests).toBe(1)
})

test('failed capabilities leave safe downloads and no local actions', async ({ page, corpus }) => {
  await page.route('**/api/opener', (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: 'unavailable', message: 'Opener unavailable' } },
    }),
  )
  const data = await openFiles(page, corpus)
  const row = await itemRow(page, data, ofType(data, 'pdf'))
  await expect(row.getByRole('link', { name: 'Download a copy' })).toBeVisible()
  await expect(row.getByRole('button', { name: 'Open in default app' })).toHaveCount(0)
  await expect(row.getByRole('button', { name: 'Copy path' })).toHaveCount(0)
})

for (const [system, label] of [
  ['macos', 'Show in Finder'],
  ['windows', 'Show in Explorer'],
  ['linux', 'Show in folder'],
] as const) {
  test(`${system} names its file manager`, async ({ page, corpus }) => {
    await capabilities(page, localCapabilities(corpus, { system }))
    const data = await openFiles(page, corpus)
    const row = await itemRow(page, data, ofType(data, 'pdf'))
    await expect(row.getByRole('button', { name: label, exact: true })).toBeVisible()
  })
}

test('Termux offers Open and Copy but no reveal or post folder', async ({ page, corpus }) => {
  await capabilities(
    page,
    localCapabilities(corpus, { system: 'android', reveal: false, folders: false }),
  )
  const data = await openFiles(page, corpus)
  const row = await itemRow(page, data, ofType(data, 'pdf'))
  await expect(row.getByRole('button', { name: 'Open in default app' })).toBeVisible()
  await expect(row.getByRole('button', { name: 'Copy path' })).toBeVisible()
  await expect(row.getByRole('button', { name: /^Show in / })).toHaveCount(0)
  await openPost(page, corpus)
  await expect(page.getByRole('button', { name: /^Open the post folder/ })).toHaveCount(0)
})

for (const shape of ['no opener', 'remote browser', 'machine name'] as const) {
  test(`${shape} grants only browser-safe View links and downloads`, async ({ page, corpus }) => {
    let value: OpenerCapabilities = remoteCapabilities()
    if (shape !== 'no opener') {
      const headers =
        shape === 'remote browser'
          ? { 'X-Forwarded-For': '198.51.100.9' }
          : { Host: `${hostname()}:${new URL(corpus.origin).port}` }
      const response = await page.request.get(`${corpus.origin}/api/opener`, { headers })
      expect(response.ok()).toBe(true)
      value = (await response.json()) as OpenerCapabilities
      expect(value.open).toBe(false)
      expect(value.root).toBeNull()
    }
    await capabilities(page, value)
    const data = await openFiles(page, corpus)
    for (const type of [
      'pdf',
      'archive',
      'program',
      'script',
      'image',
      'audio',
      'video',
    ] as const) {
      const item = ofType(data, type)
      const row = await itemRow(page, data, item)
      await expect(row.getByRole('button', { name: 'Open in default app' })).toHaveCount(0)
      await expect(row.getByRole('button', { name: 'Copy path' })).toHaveCount(0)
      await expect(row.getByRole('link', { name: 'Download a copy' })).toBeVisible()
      const view = row.getByRole('link', { name: 'View in a new tab' })
      if (['pdf', 'image', 'audio', 'video'].includes(type))
        await expect(view).toHaveAttribute('target', '_blank')
      else await expect(view).toHaveCount(0)
      expect(
        await row.evaluate((element) => {
          const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
          element.dispatchEvent(event)
          return event.defaultPrevented
        }),
      ).toBe(false)
    }
    const html = requireFixture(data.items.find((item) => item.path.endsWith('.html')))
    await expect(
      (await itemRow(page, data, html)).getByRole('link', { name: 'View in a new tab' }),
    ).toHaveCount(0)
  })
}

test('another origin and forwarded requests cannot invoke the recording opener', async ({
  page,
  corpus,
}) => {
  const data = await openFiles(page, corpus)
  const item = ofType(data, 'pdf')
  const url = `${corpus.origin}${API_PATH}/media/${encodeURIComponent(item.id)}/open`
  for (const headers of [
    { Origin: 'https://other.example' },
    { Origin: corpus.origin, 'X-Forwarded-For': '198.51.100.9' },
  ]) {
    expect((await page.request.post(url, { headers, data: { reveal: false } })).status()).toBe(403)
  }
})

test('Copy path joins original filesystem components without decoding percent signs', async ({
  page,
  context,
  browserName,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  if (browserName === 'chromium')
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  else
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: {
          writeText: (value: string) => {
            localStorage.setItem('copied-path', value)
            return Promise.resolve()
          },
        },
      })
    })
  const data = await openFiles(page, corpus)
  const item = requireFixture(
    data.items.find((entry) => entry.path.endsWith('Заметки  с пробелами, 100%25.txt')),
  )
  const row = await itemRow(page, data, item)
  await row.getByRole('button', { name: 'Copy path' }).click()
  const copied =
    browserName === 'chromium'
      ? await page.evaluate(() => navigator.clipboard.readText())
      : await page.evaluate(() => localStorage.getItem('copied-path'))
  expect(copied).toBe(sourcePath(corpus, item))
})

test('Windows copy paths preserve the root, backslash separator and literal names', async ({
  page,
  corpus,
}) => {
  await capabilities(
    page,
    localCapabilities(corpus, { system: 'windows', root: 'D:\\Library 100%25', sep: '\\' }),
  )
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: (value: string) => {
          localStorage.setItem('copied-path', value)
          return Promise.resolve()
        },
      },
    })
  })
  const data = await openFiles(page, corpus)
  const item = ofType(data, 'pdf')
  await (await itemRow(page, data, item)).getByRole('button', { name: 'Copy path' }).click()
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('copied-path')))
    .toBe(['D:\\Library 100%25', AUTHOR, ...item.path.split('/')].join('\\'))
})

for (const fallback of ['copy', 'notice'] as const) {
  test(`without clipboard API the ${fallback} fallback preserves the path`, async ({
    page,
    corpus,
  }) => {
    await capabilities(page, localCapabilities(corpus))
    await page.addInitScript((succeeds) => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined })
      document.execCommand = (command: string) => {
        const element = document.activeElement
        if (command === 'copy' && element instanceof HTMLTextAreaElement)
          localStorage.setItem('fallback-path', element.value)
        return succeeds
      }
    }, fallback === 'copy')
    const data = await openFiles(page, corpus)
    const item = ofType(data, 'pdf')
    await (await itemRow(page, data, item)).getByRole('button', { name: 'Copy path' }).click()
    if (fallback === 'copy')
      await expect
        .poll(() => page.evaluate(() => localStorage.getItem('fallback-path')))
        .toBe(sourcePath(corpus, item))
    else {
      await expect(page.getByRole('status')).toContainText(sourcePath(corpus, item))
      await page
        .locator('[data-file-notice]')
        .getByRole('button', { name: /Dismiss/ })
        .click()
      await expect(page.getByRole('status')).toHaveCount(0)
    }
  })
}
