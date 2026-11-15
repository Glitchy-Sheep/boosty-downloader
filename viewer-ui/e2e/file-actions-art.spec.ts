import {
  AUTHOR,
  capabilities,
  expect,
  localCapabilities,
  requireFixture,
  test,
} from './file-actions-fixtures'
import { openMedia } from './media-fixtures'

for (const menu of ['dropdown', 'context'] as const) {
  test(`removed audio artwork stays vivid while its ${menu} menu has focus`, async ({
    page,
    corpus,
  }) => {
    await capabilities(page, localCapabilities(corpus))
    const data = await openMedia(page, corpus, 'view=audio', AUTHOR)
    const item = requireFixture(data.items.find((entry) => entry.removed))
    const row = page.locator(`[data-media-id="${item.id}"]`)
    const art = row.locator('[data-art]')
    await row.scrollIntoViewIfNeeded()
    await page.mouse.move(4, 4)
    await expect(art).toHaveCSS('opacity', '0.35')
    if (menu === 'dropdown') await row.getByRole('button', { name: /^More for / }).click()
    else await row.click({ button: 'right', position: { x: 250, y: 30 } })
    const opened = page.getByRole('menu')
    await expect(opened).toBeVisible()
    await opened.getByRole('menuitem', { name: 'Copy path' }).focus()
    await page.mouse.move(4, 4)
    expect(await row.evaluate((element) => element.contains(document.activeElement))).toBe(false)
    await expect(art).toHaveCSS('opacity', '1')
    await page.keyboard.press('Escape')
    await expect(opened).toHaveCount(0)
    if (menu === 'dropdown')
      await expect(row.getByRole('button', { name: /^More for / })).toBeFocused()
    await page
      .getByRole('navigation', { name: 'Author', exact: true })
      .getByRole('link', { name: 'Media', exact: true })
      .focus()
    await expect(art).toHaveCSS('opacity', '0.35')
  })
}
