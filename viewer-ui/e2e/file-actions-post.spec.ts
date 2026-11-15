import { readFile } from 'node:fs/promises'
import path from 'node:path'

import type { PostDetail } from '../src/lib/api.gen'
import {
  API_PATH,
  AUTHOR,
  capabilities,
  expect,
  expectDownload,
  expectOpen,
  localCapabilities,
  openPost,
  postId,
  remoteCapabilities,
  requireFixture,
  sourcePath,
  sourceUrl,
  test,
} from './file-actions-fixtures'

test('post file cards use explicit actions, keep browser menus and open the post folder', async ({
  page,
  corpus,
  recording,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const post = await openPost(page, corpus)
  const item = requireFixture(
    post.media.find(
      (piece) => piece.kind === 'files' && piece.file_type === 'pdf' && !piece.removed,
    ),
  )
  const card = page.locator(`[data-file-card="${item.id}"]`)
  await expect(card).toHaveJSProperty('tagName', 'DIV')
  await expect(card.locator('.file-name')).toHaveText(requireFixture(item.path.split('/').at(-1)))
  await card.locator('.file-name').click()
  await card.locator('.file-name').dblclick()
  expect(
    await card.evaluate((element) => {
      const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
      element.dispatchEvent(event)
      return event.defaultPrevented
    }),
  ).toBe(false)
  await expect(page.getByRole('menu')).toHaveCount(0)
  await card.getByRole('button', { name: 'Open in default app' }).click()
  await expectOpen(corpus, recording, item)
  await expect(page).toHaveURL(new RegExp(`/p/${post.id}$`))
  await expectDownload(page, corpus, card.getByRole('link', { name: 'Download a copy' }), item)
  await page.getByRole('button', { name: /^Open the post folder/ }).click()
  await expectOpen(corpus, recording, path.dirname(path.dirname(sourcePath(corpus, item))))
})

test('retained attachments keep their actions and full long names wrap in the post', async ({
  page,
  corpus,
  recording,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const post = await openPost(page, corpus)
  const retained = requireFixture(
    post.media.find((piece) => piece.kind === 'files' && piece.removed),
  )
  const removedCard = page.locator(`[data-file-card="${retained.id}"]`)
  await removedCard.scrollIntoViewIfNeeded()
  await expect(removedCard.getByRole('toolbar').locator('[data-action]')).toHaveCount(4)
  await removedCard.getByRole('button', { name: 'Open in default app' }).click()
  await expectOpen(corpus, recording, retained)
  const launcher = requireFixture(
    post.media.find((piece) => piece.path.endsWith('.settingcontent-ms')),
  )
  const card = page.locator(`[data-file-card="${launcher.id}"]`)
  await card.scrollIntoViewIfNeeded()
  await expect(card.locator('.file-name')).toHaveText(
    requireFixture(launcher.path.split('/').at(-1)),
  )
  await card.evaluate((element: HTMLElement) => {
    element.style.width = '340px'
  })
  await expect(card.getByRole('button', { name: /^More for / })).toBeVisible()
  const wraps = await card.locator('.file-name').evaluate((element) => {
    const range = document.createRange()
    range.selectNodeContents(element)
    return range.getClientRects().length > 1 && element.scrollWidth <= element.clientWidth + 1
  })
  expect(wraps).toBe(true)
  await card.screenshot({ path: test.info().outputPath('attachment-narrow.png') })
})

test('search marks avoid generated controls and tab transitions retain players and close portals', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const post = await openPost(page, corpus)
  const first = requireFixture(post.media.find((piece) => piece.kind === 'files' && !piece.removed))
  await page.goto(`${corpus.origin}/a/${AUTHOR}/p/${post.id}?q=needle`)
  const body = page.locator('.post-body')
  await expect(body.locator('mark')).toHaveText(['needle'])
  await expect(
    body.locator('[data-page-generated] mark, [data-page-slot] mark, button mark'),
  ).toHaveCount(0)
  const player = requireFixture(await body.locator('video').first().elementHandle())
  const card = page.locator(`[data-file-card="${first.id}"]`)
  await card.evaluate((element: HTMLElement) => {
    element.style.width = '400px'
  })
  await card.getByRole('button', { name: /^More for / }).click()
  await expect(page.getByRole('menu')).toBeVisible()
  const tabs = page.getByRole('navigation', { name: 'Author', exact: true, includeHidden: true })
  await tabs
    .getByRole('link', { name: 'Media', exact: true, includeHidden: true })
    .evaluate((element: HTMLAnchorElement) => element.click())
  await expect(page.locator('.author-pane[data-tab="media"]')).toBeVisible()
  await expect(page.getByRole('menu')).toHaveCount(0)
  expect(
    await page.evaluate(() =>
      Boolean(document.activeElement?.closest('.author-pane[data-tab="posts"]')),
    ),
  ).toBe(false)
  await tabs.getByRole('link', { name: 'Posts', exact: true }).click()
  await expect(body.locator('mark')).toHaveText(['needle'])
  expect(
    await player.evaluate((element) => element === document.querySelector('.post-body video')),
  ).toBe(true)
  await page.goto(`${corpus.origin}/a/${AUTHOR}/p/${post.id}?q=Download`)
  await expect(page.locator('[data-file-card]').first()).toBeVisible()
  await expect(
    page.locator(
      '.post-body [data-page-generated] mark, .post-body [data-page-slot] mark, .post-body button mark',
    ),
  ).toHaveCount(0)
})

test('changing posts cleans attachment portals and unknown attachment URLs gain no Open', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  await page.route(`**${API_PATH}/posts/${postId()}`, async (route) => {
    const response = await route.fetch()
    const post = (await response.json()) as PostDetail
    await route.fulfill({
      json: {
        ...post,
        body_html: `${post.body_html}<div class="attachments"><a class="attachment" href="/media/${AUTHOR}/unknown.pdf"><span class="attachment-name">Unknown attachment</span></a></div>`,
      },
    })
  })
  const post = await openPost(page, corpus)
  const item = requireFixture(post.media.find((piece) => piece.kind === 'files'))
  const unknown = page.locator('.attachment').filter({ hasText: 'Unknown attachment' })
  await expect(unknown.getByRole('button', { name: 'Open in default app' })).toHaveCount(0)
  const card = page.locator(`[data-file-card="${item.id}"]`)
  await card.evaluate((element: HTMLElement) => {
    element.style.width = '400px'
  })
  await card.getByRole('button', { name: /^More for / }).click()
  await page
    .locator('.post-body')
    .getByRole('link', { name: 'Another file post', includeHidden: true })
    .evaluate((element: HTMLAnchorElement) => element.click())
  await expect(page).toHaveURL(new RegExp(`/p/${postId(2)}$`))
  await expect(page.getByRole('menu')).toHaveCount(0)
  await expect(page.locator(`[data-file-card="${item.id}"]`)).toHaveCount(0)
  await expect(page.locator('[data-file-card]')).toHaveCount(1)
})

test('inline post media and its image viewer have no per-file actions', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  await openPost(page, corpus)
  const body = page.locator('.post-body')
  for (const tag of ['video', 'audio']) {
    const media = body.locator(tag)
    await expect(media).toHaveCount(2)
    expect(
      await media.evaluateAll((elements) =>
        elements.every((element) => !element.parentElement?.querySelector('[data-action]')),
      ),
    ).toBe(true)
  }
  await body
    .getByRole('button', { name: /^Open image:/ })
    .first()
    .click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('[data-action]')).toHaveCount(0)
})

test('post folders require both a stored folder and folder capability', async ({
  page,
  corpus,
}) => {
  await capabilities(page, localCapabilities(corpus))
  const locked = await openPost(page, corpus, 3)
  expect(locked.has_folder).toBe(false)
  await expect(page.getByRole('button', { name: /^Open the post folder/ })).toHaveCount(0)
  await capabilities(page, remoteCapabilities())
  await openPost(page, corpus)
  await expect(page.getByRole('button', { name: /^Open the post folder/ })).toHaveCount(0)
})

test('loading an HTML attachment downloads its real bytes and executes no script', async ({
  page,
  corpus,
}) => {
  const post = await openPost(page, corpus)
  const item = requireFixture(post.media.find((piece) => piece.path.endsWith('.html')))
  const executed: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/file-attachment-executed')) executed.push(request.url())
  })
  const response = await page.request.get(`${corpus.origin}${sourceUrl(item)}`)
  expect(response.headers()['content-disposition']).toContain('attachment')
  expect(response.headers()['x-content-type-options']).toBe('nosniff')
  const download = page.waitForEvent('download')
  const navigation = page.goto(`${corpus.origin}${sourceUrl(item)}`).catch((error: unknown) => {
    expect(String(error)).toMatch(/download|aborted|ERR_ABORTED|NS_BINDING_ABORTED/i)
  })
  const saved = await download
  await navigation
  expect(await readFile(requireFixture(await saved.path()))).toEqual(
    await readFile(sourcePath(corpus, item)),
  )
  expect(executed).toEqual([])
  expect(await page.evaluate(() => Object.hasOwn(window, '__fileAttack'))).toBe(false)
})
