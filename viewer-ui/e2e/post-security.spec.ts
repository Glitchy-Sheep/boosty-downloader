import { API_PATH, POSTS, expect, openPost, pane, test } from './post-fixtures'

test('canonical post metadata and authored HTML-looking text remain inert', async ({
  page,
  corpus,
}) => {
  const post = await openPost(page, corpus, POSTS.security)
  await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText(post.title)
  await expect(pane(page)).toContainText('<script>window.__postAttack=3</script>')
  await expect(
    pane(page).getByRole('button', { name: '#<svg onload="window.__postAttack=2">', exact: true }),
  ).toBeVisible()
  await expect(pane(page).getByText('Unsafe destination', { exact: true })).toBeVisible()
  await expect(
    pane(page).getByText('<img src=x onerror="window.__postAttack=5">', { exact: true }),
  ).toBeVisible()
  await expect(pane(page).locator('a[href^="javascript:"]')).toHaveCount(0)
  await expect(pane(page).locator('script, iframe, [onerror], [onload]')).toHaveCount(0)
  expect(await page.evaluate(() => Reflect.get(window, '__postAttack'))).toBeUndefined()

  const body = await page.request.get(`${corpus.origin}${API_PATH}/posts/${POSTS.security}`)
  expect(body.ok()).toBe(true)
  const saved = (await body.json()) as { body_html: string }
  expect(saved.body_html).toContain('&lt;script&gt;')
  expect(saved.body_html).not.toContain('href="javascript:')
})

test('the complete viewer refuses framing even from its own origin', async ({ page, corpus }) => {
  await openPost(page, corpus, POSTS.reader)
  const response = await page.request.get(`${corpus.origin}/a/reader_checks/p/${POSTS.reader}`)
  expect(response.headers()['content-security-policy']).toContain("frame-ancestors 'none'")
  expect(response.headers()['x-frame-options']).toBe('DENY')

  await page.evaluate((url) => {
    const frame = document.createElement('iframe')
    frame.id = 'security-frame'
    frame.src = url
    frame.addEventListener('load', () => {
      frame.dataset.loaded = 'true'
    })
    document.body.append(frame)
  }, `${corpus.origin}/a/reader_checks/p/${POSTS.reader}`)
  await expect(page.locator('#security-frame')).toHaveAttribute('data-loaded', 'true')
  const inaccessible = await page
    .locator('#security-frame')
    .evaluate((frame: HTMLIFrameElement) => {
      try {
        return frame.contentDocument === null
      } catch {
        return true
      }
    })
  expect(inaccessible).toBe(true)
})
