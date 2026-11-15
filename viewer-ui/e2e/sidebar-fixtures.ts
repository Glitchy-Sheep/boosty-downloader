import type { Locator, Page } from '@playwright/test'

import { expect } from './post-fixtures'
import { requireFixture } from './required-fixture'

export const SIDEBAR_STORAGE = 'boosty-viewer.sidebar'
export const WIDTH = { min: 260, default: 360, max: 640 } as const
export type SidebarPreference = { width: number; collapsed: boolean }
export type WidthFrame = { time: number; width: number }

export function panel(page: Page): Locator {
  return page.locator('#sidebar[data-panel]')
}

export function content(page: Page): Locator {
  return page.locator('#author-post-sidebar')
}

export function separator(page: Page): Locator {
  return page.getByRole('separator', { name: 'Sidebar width', exact: true })
}

export function toggle(page: Page): Locator {
  return page.locator('header button[aria-controls="author-post-sidebar"]')
}

export function layout(page: Page): Locator {
  return page.locator('[data-sidebar-layout]')
}

export async function width(page: Page): Promise<number> {
  return panel(page).evaluate((element) => element.getBoundingClientRect().width)
}

export async function expectWidth(page: Page, expected: number): Promise<void> {
  await expect.poll(async () => Math.abs((await width(page)) - expected)).toBeLessThanOrEqual(0.5)
}

export async function seedPreference(page: Page, value: string): Promise<void> {
  await page.addInitScript(
    ({ key, value }) => {
      const marker = `${key}.test-seeded`
      if (sessionStorage.getItem(marker)) return
      localStorage.setItem(key, value)
      sessionStorage.setItem(marker, 'true')
    },
    { key: SIDEBAR_STORAGE, value },
  )
}

export async function savedPreference(page: Page): Promise<SidebarPreference> {
  return page.evaluate((key) => {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
    if (
      typeof value !== 'object' ||
      value === null ||
      !('width' in value) ||
      typeof value.width !== 'number' ||
      !('collapsed' in value) ||
      typeof value.collapsed !== 'boolean'
    )
      throw new Error('No valid saved sidebar preference')
    return { width: value.width, collapsed: value.collapsed }
  }, SIDEBAR_STORAGE)
}

export async function frames(page: Page, count = 2): Promise<void> {
  await page.evaluate(async (count) => {
    for (let index = 0; index < count; index++)
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  }, count)
}

export async function dragTo(page: Page, target: number): Promise<void> {
  const bounds = requireFixture(await separator(page).boundingBox())
  const start = bounds.x + bounds.width / 2
  const y = bounds.y + Math.min(100, bounds.height / 2)
  const end = start + target - (await width(page))
  await page.mouse.move(start, y)
  await page.mouse.down()
  await page.mouse.move(end, y, { steps: Math.max(1, Math.ceil(Math.abs(end - start) / 10)) })
  await page.mouse.up()
  await expectWidth(page, Math.min(WIDTH.max, Math.max(WIDTH.min, target)))
}

export async function blurControl(page: Page): Promise<void> {
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  })
}

export async function physicalBracket(page: Page, key = 'х'): Promise<void> {
  await page.evaluate((key) => {
    ;(document.activeElement ?? document.body).dispatchEvent(
      new KeyboardEvent('keydown', {
        code: 'BracketLeft',
        key,
        bubbles: true,
        cancelable: true,
      }),
    )
  }, key)
}

export async function widthFrames(page: Page, action: 'toggle' | 'reset'): Promise<WidthFrame[]> {
  return page.evaluate(async (action) => {
    const panel = document.querySelector('#sidebar[data-panel]')
    if (!panel) throw new Error('No sidebar panel')
    const began = performance.now()
    const readings: WidthFrame[] = []
    const read = (): void => {
      readings.push({ time: performance.now() - began, width: panel.getBoundingClientRect().width })
    }
    read()
    if (action === 'toggle')
      document
        .querySelector<HTMLButtonElement>('header button[aria-controls="author-post-sidebar"]')
        ?.click()
    else {
      const edge = document.querySelector('[role="separator"][aria-label="Sidebar width"]')
      if (!edge) throw new Error('No sidebar resize edge')
      const box = edge.getBoundingClientRect()
      edge.dispatchEvent(
        new MouseEvent('dblclick', {
          bubbles: true,
          cancelable: true,
          clientX: box.x + box.width / 2,
          clientY: box.y + 20,
        }),
      )
    }
    await new Promise<void>((resolve) => {
      const tick = (): void => {
        read()
        if (performance.now() - began < 420) requestAnimationFrame(tick)
        else resolve()
      }
      requestAnimationFrame(tick)
    })
    return readings
  }, action)
}
