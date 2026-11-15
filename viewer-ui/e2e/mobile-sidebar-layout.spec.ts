import type { Author } from '../src/lib/api.gen'
import { API_PATH, expect, openMedia, readyPlayer, tab, test } from './media-fixtures'
import {
  closeMobileSidebar,
  expectFullMobilePost,
  openMobileSidebar,
  postElement,
  sheet,
  timeline,
} from './mobile-sidebar-fixtures'
import { seedPreference, toggle } from './sidebar-fixtures'
import { requireFixture } from './required-fixture'

const VIEWPORTS = [
  { width: 360, height: 740 },
  { width: 390, height: 844 },
  { width: 820, height: 1180 },
]

for (const viewport of VIEWPORTS) {
  for (const colorScheme of ['dark', 'light'] as const) {
    test(`${viewport.width}x${viewport.height} ${colorScheme}: long counts, errors and a playing global track leave a usable timeline`, async ({
      page,
      corpus,
    }, info) => {
      await page.setViewportSize(viewport)
      await page.emulateMedia({ colorScheme })
      await seedPreference(page, JSON.stringify({ width: 360, collapsed: false }))
      const response = await page.request.get(`${corpus.origin}${API_PATH}`)
      expect(response.ok()).toBe(true)
      const author = (await response.json()) as Author
      await page.route(`**${API_PATH}`, (route) =>
        route.fulfill({
          json: {
            ...author,
            posts: 123456789,
            unseen: 12345678,
            favorites: 7654321,
          } satisfies Author,
        }),
      )
      await page.route(`**${API_PATH}/tags`, (route) =>
        route.fulfill({
          status: 503,
          json: { error: { code: 'unavailable', message: 'Tags are temporarily unavailable.' } },
        }),
      )
      const data = await openMedia(page, corpus, 'view=audio')
      const item = requireFixture(data.items[0])
      await page
        .locator(`[data-audio-list] [data-media-id="${item.id}"]`)
        .getByRole('button', { name: /^Play / })
        .click()
      const bar = page.getByRole('region', { name: 'Player', exact: true })
      const audio = bar.locator('audio')
      await readyPlayer(audio)
      await expect
        .poll(() => audio.evaluate((element: HTMLMediaElement) => element.paused))
        .toBe(false)
      const player = requireFixture(await audio.elementHandle())
      await tab(page, 'Posts')
      await expect(postElement(page)).toBeVisible()
      const reader = requireFixture(await postElement(page).elementHandle())
      if (viewport.width < 768) {
        await expectFullMobilePost(page)
        await expect(toggle(page)).toHaveAccessibleName('Show sidebar')
      }
      await openMobileSidebar(page)
      await expect(timeline(page).getByRole('alert')).toHaveText(
        'Tags are temporarily unavailable.',
      )
      await expect(timeline(page)).toContainText('123,456,789 posts')
      await expect(timeline(page)).toContainText('12,345,678 unseen')
      await expect(timeline(page)).toContainText('7,654,321 favorites')
      await timeline(page).getByRole('button', { name: 'Unseen', exact: true }).click()
      await expect(
        timeline(page).getByRole('button', { name: 'Clear filters', exact: true }),
      ).toBeVisible()
      await expect(timeline(page).getByRole('combobox', { name: 'Jump to month' })).toBeEnabled()
      await expect(
        timeline(page).getByRole('button', { name: 'Mark posts', exact: true }),
      ).toBeEnabled()
      const bounds = requireFixture(await timeline(page).boundingBox())
      const list = timeline(page).locator('[data-post-list]')
      const listBox = requireFixture(await list.boundingBox())
      expect(listBox.height).toBeGreaterThanOrEqual(120)
      expect(listBox.y + listBox.height).toBeLessThanOrEqual(viewport.height + 0.5)
      expect(
        await timeline(page).evaluate((element) => element.scrollWidth <= element.clientWidth),
      ).toBe(true)
      const controls = await timeline(page)
        .locator('button:visible, input:visible, select:visible')
        .evaluateAll((elements) =>
          elements
            .filter((element) => !element.closest('[data-post-list]'))
            .map((element) => {
              const box = element.getBoundingClientRect()
              return { left: box.left, right: box.right, top: box.top, bottom: box.bottom }
            }),
        )
      expect(
        controls
          .filter((box) => box.top < listBox.y)
          .every(
            (box) =>
              box.left >= bounds.x - 0.5 &&
              box.right <= bounds.x + bounds.width + 0.5 &&
              box.top >= 0 &&
              box.bottom <= viewport.height,
          ),
      ).toBe(true)
      if (viewport.width < 768) {
        const dialog = requireFixture(await sheet(page).boundingBox())
        expect(Math.abs(dialog.width - Math.min(viewport.width * 0.88, 400))).toBeLessThanOrEqual(
          0.5,
        )
        expect(dialog.height).toBe(viewport.height)
        await expect(page.getByRole('region', { name: 'Selected post', exact: true })).toHaveCount(
          0,
        )
        await expect(page.getByRole('region', { name: 'Player', exact: true })).toHaveCount(0)
      }
      const firstRow = list.locator('[data-post-id]').first()
      const countBadges = firstRow.locator('span[title]').filter({ has: page.locator('svg') })
      await expect(countBadges).toHaveCount(4)
      const paint = await firstRow.evaluate((row) => {
        const counts = [...row.querySelectorAll<HTMLElement>('span[title]')].filter((element) =>
          element.querySelector('svg'),
        )
        const container = counts[0]?.parentElement
        const missing = row.querySelector<HTMLElement>('[title$="missing pieces"]')
        const date = row.querySelector('time')
        if (!container || !missing || !date) throw new Error('Missing stressed row metadata')
        const clip = container.getBoundingClientRect()
        const status = missing.getBoundingClientRect()
        const clipped = ['hidden', 'clip'].includes(getComputedStyle(container).overflowX)
        const right = Math.max(...counts.map((count) => count.getBoundingClientRect().right))
        return {
          clipped,
          intrinsicRight: right,
          clipRight: clip.right,
          paintedRight: clipped ? Math.min(right, clip.right) : right,
          statusLeft: status.left,
          statusRight: status.right,
          dateRight: date.getBoundingClientRect().right,
          countsLeft: clip.left,
          rowRight: row.getBoundingClientRect().right,
        }
      })
      await info.attach('narrow-row-metadata.json', {
        body: JSON.stringify(paint),
        contentType: 'application/json',
      })
      expect(paint.paintedRight).toBeLessThanOrEqual(paint.statusLeft - 1)
      expect(paint.dateRight).toBeLessThanOrEqual(paint.countsLeft)
      expect(paint.statusRight).toBeLessThanOrEqual(paint.rowRight)
      expect(
        await player.evaluate(
          (element) =>
            element instanceof HTMLMediaElement &&
            !element.paused &&
            element === document.querySelector('[aria-label="Player"] audio'),
        ),
      ).toBe(true)
      expect(
        await reader.evaluate(
          (element) => element === document.querySelector('[aria-label="Selected post"]'),
        ),
      ).toBe(true)
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth <= innerWidth &&
            document.documentElement.scrollHeight <= innerHeight + 1,
        ),
      ).toBe(true)
      await info.attach(`mobile-sidebar-${viewport.width}-${colorScheme}`, {
        body: await page.screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
      })
      await closeMobileSidebar(page)
      await expect(bar).toBeVisible()
      await expect
        .poll(() => audio.evaluate((element: HTMLMediaElement) => element.paused))
        .toBe(false)
    })
  }
}
