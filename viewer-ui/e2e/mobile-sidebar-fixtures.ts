import { expect, type Locator, type Page } from '@playwright/test'

import { toggle } from './sidebar-fixtures'

export function sheet(page: Page): Locator {
  return page.getByRole('dialog', { name: 'Posts', exact: true })
}

export function postElement(page: Page): Locator {
  return page.locator('[aria-label="Selected post"]')
}

export function timeline(page: Page): Locator {
  return page.locator('aside[aria-label^="Posts of "]')
}

export async function openMobileSidebar(page: Page): Promise<void> {
  if ((page.viewportSize()?.width ?? 1440) >= 768) return
  await expect(toggle(page)).toBeEnabled()
  await toggle(page).click()
  await expect(sheet(page)).toBeVisible()
}

export async function closeMobileSidebar(page: Page): Promise<void> {
  if ((page.viewportSize()?.width ?? 1440) >= 768) return
  await sheet(page).getByRole('button', { name: 'Close sidebar', exact: true }).click()
  await expect(sheet(page)).toHaveCount(0)
}

export async function expectFullMobilePost(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.locator('[data-sidebar-layout]').evaluate((group) => {
        const sidebar = group.querySelector('#sidebar[data-panel]')?.getBoundingClientRect()
        const post = group.querySelector('#post[data-panel]')?.getBoundingClientRect()
        const bounds = group.getBoundingClientRect()
        if (!sidebar || !post) throw new Error('Missing responsive panels')
        return Math.max(
          sidebar.width,
          Math.abs(post.width - bounds.width),
          Math.abs(post.height - bounds.height),
          Math.abs(post.x - bounds.x),
          Math.abs(post.y - bounds.y),
        )
      }),
    )
    .toBeLessThanOrEqual(0.5)
}
