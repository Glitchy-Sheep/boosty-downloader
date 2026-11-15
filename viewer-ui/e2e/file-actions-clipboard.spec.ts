import type { Locator, Page } from '@playwright/test'

import type { MediaItem } from '../src/lib/api.gen'
import {
  AUTHOR,
  capabilities,
  expect,
  itemRow,
  localCapabilities,
  openFiles,
  requireFixture,
  sourcePath,
  test,
} from './file-actions-fixtures'
import { openMedia, type MediaCorpus } from './media-fixtures'

test.describe.configure({ mode: 'serial' })

type CopyAttempt = {
  path: string | null
  selectionStart: number | null
  selectionEnd: number | null
  inMenu: boolean
  copied: boolean
}

declare global {
  interface Window {
    fileClipboardProbe?: { attempts: CopyAttempt[]; readText?: () => Promise<string> }
  }
}

async function observeLegacyClipboard(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const clipboard = navigator.clipboard
    const probe = {
      attempts: [] as CopyAttempt[],
      ...(clipboard ? { readText: clipboard.readText.bind(clipboard) } : {}),
    }
    window.fileClipboardProbe = probe
    const execute = document.execCommand.bind(document)
    Object.defineProperty(navigator, 'clipboard', { value: undefined })
    document.execCommand = (command: string) => {
      const field = document.activeElement
      const selected = field instanceof HTMLTextAreaElement ? field : null
      const copied = execute(command)
      if (command === 'copy')
        probe.attempts.push({
          path: selected?.value ?? null,
          selectionStart: selected?.selectionStart ?? null,
          selectionEnd: selected?.selectionEnd ?? null,
          inMenu: Boolean(selected?.closest('[role="menu"]')),
          copied,
        })
      return copied
    }
  })
}

type CopySurface = 'dropdown' | 'context' | 'fullscreen'
type OpenCopyMenu = { item: MediaItem; returnFocus: Locator; notice: Locator }

async function openCopyMenu(
  page: Page,
  corpus: MediaCorpus,
  surface: CopySurface,
): Promise<OpenCopyMenu> {
  if (surface === 'fullscreen') {
    const media = await openMedia(page, corpus, 'view=images', AUTHOR)
    const item = requireFixture(media.items[0])
    await page.locator(`[data-media-id="${item.id}"]`).click()
    const dialog = page.getByRole('dialog', { name: 'Media viewer' })
    const more = dialog.getByRole('button', { name: /^More for / })
    await more.click()
    return { item, returnFocus: more, notice: dialog.locator('[data-file-notice]') }
  }
  if (surface === 'dropdown') await page.setViewportSize({ width: 500, height: 1000 })
  const files = await openFiles(page, corpus)
  const item = requireFixture(files.items.find((file) => file.path.includes('100%25')))
  const row = await itemRow(page, files, item)
  const more = row.getByRole('button', { name: /^More for / })
  const postLink = row.getByRole('link', { name: 'File action post 1', exact: true })
  if (surface === 'dropdown') await more.click()
  else {
    await postLink.focus()
    await row.locator('.file-name').click({ button: 'right' })
  }
  return {
    item,
    returnFocus: surface === 'dropdown' ? more : page.locator('body'),
    notice: page.locator('[data-file-notice]'),
  }
}

for (const surface of ['dropdown', 'context', 'fullscreen'] as const) {
  test(`native legacy copy from the ${surface} menu keeps the field selected and restores focus`, async ({
    page,
    context,
    browserName,
    corpus,
  }) => {
    if (browserName === 'chromium')
      await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await observeLegacyClipboard(page)
    await capabilities(page, localCapabilities(corpus))
    const { item, returnFocus, notice } = await openCopyMenu(page, corpus, surface)
    await page.getByRole('menuitem', { name: 'Copy path', exact: true }).click()
    const path = sourcePath(corpus, item)
    expect(await page.evaluate(() => window.fileClipboardProbe?.attempts)).toEqual([
      { path, selectionStart: 0, selectionEnd: path.length, inMenu: true, copied: true },
    ])
    if (browserName === 'chromium')
      expect(await page.evaluate(() => window.fileClipboardProbe?.readText?.())).toBe(path)
    await expect(notice.getByRole('status')).toContainText('Path copied')
    await expect(notice.getByRole('status')).toContainText(path)
    await expect(page.getByRole('menu')).toHaveCount(0)
    await expect(returnFocus).toBeFocused()
    await expect(page.getByRole('textbox', { name: 'Path to copy' })).toHaveCount(0)
  })
}
