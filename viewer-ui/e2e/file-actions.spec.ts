import {
  capabilities,
  expect,
  expectDownload,
  expectOpen,
  itemRow,
  localCapabilities,
  ofType,
  openFiles,
  opened,
  requireFixture,
  test,
} from './file-actions-fixtures'

test('explicit file actions preserve exact paths and bytes while rows do nothing', async ({
  page,
  corpus,
  recording,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  const item = ofType(data, 'pdf')
  const row = await itemRow(page, data, item)
  const name = row.locator('.file-name')
  await expect(name).toHaveText(requireFixture(item.path.split('/').at(-1)))
  await expect(row).toContainText('PDF document')
  await expect(row).not.toContainText('Original server filename')
  await expect(row.getByRole('button')).toHaveCount(3)
  await expect(row.getByRole('link', { name: 'Download a copy' })).toBeVisible()
  await name.click()
  await name.dblclick()
  expect((await opened(corpus)).slice(recording.before)).toEqual([])
  await row.getByRole('button', { name: 'Open in default app' }).press('Enter')
  await expectOpen(corpus, recording, item)
  await row.getByRole('button', { name: 'Show in Finder' }).click()
  await expectOpen(corpus, recording, item, 'reveal')
  await expectDownload(page, corpus, row.getByRole('link', { name: 'Download a copy' }), item)
  await expect(page).toHaveURL(/view=files$/)
})

test('a double-click opens once and a drag released on Open never opens', async ({
  page,
  corpus,
  recording,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  const item = ofType(data, 'pdf')
  const row = await itemRow(page, data, item)
  const open = row.getByRole('button', { name: 'Open in default app' })
  await open.dblclick()
  await expectOpen(corpus, recording, item)
  const target = requireFixture(await open.boundingBox())
  const name = requireFixture(await row.locator('.file-name').boundingBox())
  await page.mouse.move(name.x + 2, name.y + 2)
  await page.mouse.down()
  await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2)
  await page.mouse.up()
  await expect(open).toBeEnabled()
  expect((await opened(corpus)).slice(recording.before)).toEqual(recording.expected)
})

test('one in-flight action cannot open again', async ({ page, corpus, recording }) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  const item = ofType(data, 'pdf')
  const row = await itemRow(page, data, item)
  let release: (() => void) | undefined
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/media/*/open', async (route) => {
    const response = await route.fetch()
    await pending
    await route.fulfill({ response })
  })
  const open = row.getByRole('button', { name: 'Open in default app' })
  await open.click()
  await expect(open).toBeDisabled()
  await open.dispatchEvent('click')
  await expectOpen(corpus, recording, item)
  requireFixture(release)()
  await expect(open).toBeEnabled()
})

test('right-click actions and keyboard roving preserve the post link browser menu', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  const row = await itemRow(page, data, ofType(data, 'pdf'))
  const toolbar = row.getByRole('toolbar')
  await toolbar.getByRole('button', { name: 'Open in default app' }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(toolbar.getByRole('button', { name: 'Show in Finder' })).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect(toolbar.getByRole('button', { name: 'Copy path' })).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect(toolbar.getByRole('link', { name: 'Download a copy' })).toBeFocused()
  await page.keyboard.press('Tab')
  expect(await toolbar.evaluate((element) => element.contains(document.activeElement))).toBe(false)
  await row.locator('.file-name').click({ button: 'right' })
  const menu = page.getByRole('menu')
  await expect(menu.getByRole('menuitem')).toHaveText([
    'Open in default app',
    'Show in Finder',
    'Copy path',
    'Download a copy',
  ])
  await page.keyboard.press('Escape')
  const prevented = await row
    .getByRole('link', { name: 'File action post 1', exact: true })
    .evaluate((element) => {
      const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2 })
      element.dispatchEvent(event)
      return event.defaultPrevented
    })
  expect(prevented).toBe(false)
  await expect(menu).toHaveCount(0)
})

test('a held More key and a dragged right-click release do not activate Open', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  const row = await itemRow(page, data, ofType(data, 'pdf'))
  await row.evaluate((element: HTMLElement) => {
    element.style.width = '500px'
  })
  const more = row.getByRole('button', { name: /^More for / })
  await expect(more).toBeVisible()
  await more.focus()
  await page.keyboard.down('Enter')
  await expect(page.getByRole('menu')).toBeVisible()
  await page.keyboard.down('Enter')
  await page.keyboard.down('Enter')
  await page.keyboard.up('Enter')
  await expect(page.getByRole('menu')).toBeVisible()
  await page.keyboard.press('Escape')
  const point = requireFixture(await row.locator('.file-name').boundingBox())
  await page.mouse.move(point.x + 2, point.y + 2)
  await page.mouse.down({ button: 'right' })
  await row.dispatchEvent('contextmenu', { button: 2 })
  const open = page.getByRole('menuitem', { name: 'Open in default app', exact: true })
  await expect(open).toBeVisible()
  const bounds = requireFixture(await open.boundingBox())
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
  await page.mouse.up({ button: 'right' })
  await page.keyboard.press('Escape')
})

test('programs and scripts explain Open before activation, with no confirmation', async ({
  page,
  corpus,
  recording,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  for (const [type, mark, hint] of [
    ['program', 'Program', 'The program starts'],
    ['script', 'Script', 'The script may run'],
  ] as const) {
    const item = ofType(data, type)
    const row = await itemRow(page, data, item)
    await expect(row.getByText(mark, { exact: true })).toBeVisible()
    await row.getByRole('button', { name: 'Open in default app' }).hover()
    await expect(page.getByRole('tooltip')).toContainText(hint)
    await row.locator('.file-name').click({ button: 'right' })
    const open = page.getByRole('menuitem', { name: 'Open in default app', exact: true })
    await expect(open).toContainText(hint)
    await open.click()
    await expectOpen(corpus, recording, item)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
})

test('removed rows retain every action and record the same exact path', async ({
  page,
  corpus,
  recording,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  const item = ofType(data, 'pdf', true)
  const row = await itemRow(page, data, item)
  await expect(row).toHaveAttribute('data-removed', '')
  await expect(row.getByRole('toolbar').locator('[data-action]')).toHaveCount(4)
  await row.getByRole('button', { name: 'Open in default app' }).click()
  await expectOpen(corpus, recording, item)
  await expectDownload(page, corpus, row.getByRole('link', { name: 'Download a copy' }), item)
})

test('folding follows the row width at 512px while the window remains wide', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const data = await openFiles(page, corpus)
  const row = await itemRow(page, data, ofType(data, 'pdf'))
  for (const width of [512, 511.75, 512.25]) {
    await row.evaluate((element: HTMLElement, size) => {
      element.style.width = `${size}px`
    }, width)
    await expect(row.getByRole('button', { name: 'Open in default app' })).toHaveCount(
      width < 512 ? 0 : 1,
    )
    await expect(row.getByRole('button', { name: /^More for / })).toHaveCount(width < 512 ? 1 : 0)
  }
})
