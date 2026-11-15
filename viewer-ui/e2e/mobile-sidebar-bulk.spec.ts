import type { BulkMarksProgressResponse, BulkMarksRequest } from '../src/lib/api.gen'
import { expect, test } from './marks-fixtures'
import {
  closeMobileSidebar,
  expectFullMobilePost,
  openMobileSidebar,
  postElement,
  sheet,
  timeline,
} from './mobile-sidebar-fixtures'
import { frames, toggle } from './sidebar-fixtures'

const API = '/api/authors/marks_checks'
const POST = '30000000-0000-4000-8000-000000000001'

test.use({ viewport: { width: 360, height: 740 } })

for (const colorScheme of ['dark', 'light'] as const) {
  for (const outcome of ['success', 'failure'] as const) {
    test(`${colorScheme}: bulk ${outcome} survives sheet closure, Media and docking`, async ({
      page,
      marks,
    }, info) => {
      await page.emulateMedia({ colorScheme })
      await page.goto(`${marks.origin}/a/marks_checks/p/${POST}?tag=stream`)
      await expect(postElement(page).getByRole('heading', { level: 1 })).toHaveText('Unseen stream')
      await expectFullMobilePost(page)
      await openMobileSidebar(page)
      let release = (): void => {}
      const held = new Promise<void>((resolve) => {
        release = resolve
      })
      let requested: BulkMarksRequest | undefined
      let writes = 0
      const progress: BulkMarksProgressResponse = {
        active: true,
        total: 4,
        completed: 2,
        changed: 1,
      }
      await page.route(`**${API}/marks/progress`, (route) => route.fulfill({ json: progress }))
      await page.route(`**${API}/marks`, async (route) => {
        writes += 1
        requested = route.request().postDataJSON() as BulkMarksRequest
        await held
        if (outcome === 'success') await route.continue()
        else
          await route.fulfill({
            status: 503,
            json: { error: { code: 'unavailable', message: 'Marking interrupted. Please retry.' } },
          })
      })
      try {
        await sheet(page).getByRole('button', { name: 'Mark posts', exact: true }).click()
        await page.getByRole('menuitem', { name: 'Mark all as seen', exact: true }).click()
        const confirm = page.getByRole('dialog', { name: 'Mark 3 posts as seen?', exact: true })
        await expect(confirm).toBeVisible()
        await confirm.getByRole('button', { name: 'Mark as seen', exact: true }).click()
        const operation = page.getByRole('dialog', { name: 'Marking posts', exact: true })
        await expect(operation).toBeVisible()
        const confirmedFocus = await operation.evaluate((element) => ({
          inside: element.contains(document.activeElement),
          focused: document.activeElement?.outerHTML.slice(0, 500),
        }))
        await info.attach('bulk-confirm-focus.json', {
          body: JSON.stringify(confirmedFocus),
          contentType: 'application/json',
        })
        expect(confirmedFocus.inside).toBe(true)
        await page.keyboard.press('Tab')
        expect(
          await operation.evaluate((element) => element.contains(document.activeElement)),
        ).toBe(true)
        await page.keyboard.press('Escape')
        await expect(operation).toHaveCount(0)
        await expect(sheet(page)).toBeVisible()
        await sheet(page)
          .getByRole('button', { name: 'Show marking progress', exact: true })
          .click()
        await expect(operation).toContainText('2 of 4 posts processed')
        await expect(operation).toContainText('1 post changed')
        expect(requested).toMatchObject({ seen: true, filters: { tag: 'stream', unseen: false } })
        const bounds = await operation.evaluate((element) => {
          const box = element.getBoundingClientRect()
          return {
            left: box.left,
            right: box.right,
            top: box.top,
            bottom: box.bottom,
            scrollWidth: element.scrollWidth,
            clientWidth: element.clientWidth,
          }
        })
        expect(bounds.left).toBeGreaterThanOrEqual(0)
        expect(bounds.right).toBeLessThanOrEqual(360)
        expect(bounds.top).toBeGreaterThanOrEqual(0)
        expect(bounds.bottom).toBeLessThanOrEqual(740)
        expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.clientWidth)
        await info.attach(`mobile-bulk-progress-${colorScheme}-${outcome}`, {
          body: await page.screenshot({ animations: 'disabled' }),
          contentType: 'image/png',
        })
        await operation.getByRole('button', { name: 'Close', exact: true }).click()
        await expect(sheet(page)).toBeVisible()
        await expect(
          sheet(page).getByRole('button', { name: 'Show marking progress', exact: true }),
        ).toBeEnabled()
        await closeMobileSidebar(page)
        await openMobileSidebar(page)
        await sheet(page)
          .getByRole('button', { name: 'Show marking progress', exact: true })
          .click()
        await expect(operation).toContainText('2 of 4 posts processed')
        await page.keyboard.press('Escape')
        await expect(operation).toHaveCount(0)
        await expect(sheet(page)).toBeVisible()
        await closeMobileSidebar(page)
        await page.setViewportSize({ width: 820, height: 1180 })
        await expect(
          timeline(page).getByRole('button', { name: 'Show marking progress', exact: true }),
        ).toBeEnabled()
        const tabs = page.getByRole('navigation', { name: 'Author', exact: true })
        await tabs.getByRole('link', { name: 'Media', exact: true }).click()
        await expect(toggle(page)).toBeDisabled()
        expect(writes).toBe(1)
      } finally {
        release()
      }
      await expect(page.getByRole('region', { name: 'Author media' })).toBeVisible()
      await page
        .getByRole('navigation', { name: 'Author', exact: true })
        .getByRole('link', { name: 'Posts', exact: true })
        .click()
      await expect(
        timeline(page).getByRole('button', { name: 'Mark posts', exact: true }),
      ).toBeEnabled()
      await page.setViewportSize({ width: 360, height: 740 })
      await openMobileSidebar(page)
      await sheet(page).getByRole('button', { name: 'Mark posts', exact: true }).click()
      await page.getByRole('menuitem', { name: 'Last marking result', exact: true }).click()
      const result = page.getByRole('dialog', {
        name: outcome === 'success' ? 'Posts marked' : 'Marking failed',
        exact: true,
      })
      await expect(result).toContainText(
        outcome === 'success' ? 'Marked 3 posts as seen.' : 'Marking interrupted. Please retry.',
      )
      if (outcome === 'failure') {
        await expect(
          result.getByRole('button', { name: 'Retry marking', exact: true }),
        ).toBeVisible()
        await info.attach(`mobile-bulk-error-${colorScheme}`, {
          body: await page.screenshot({ animations: 'disabled' }),
          contentType: 'image/png',
        })
      }
      expect(writes).toBe(1)
      await result.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(sheet(page)).toBeVisible()
      await frames(page, 3)
      expect(
        await sheet(page).evaluate((element) => element.contains(document.activeElement)),
      ).toBe(true)
    })
  }
}
