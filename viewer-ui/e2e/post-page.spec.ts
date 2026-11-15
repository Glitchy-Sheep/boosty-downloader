import { requireFixture } from './required-fixture'
import {
  API_PATH,
  POSTS,
  author,
  detail,
  expect,
  list,
  openPost,
  pane,
  postPath,
  readyPlayer,
  sidebar,
  test,
} from './post-fixtures'

for (const colorScheme of ['dark', 'light'] as const) {
  test(`${colorScheme}: the complete page keeps authored order, links and downloaded history`, async ({
    page,
    corpus,
  }, info) => {
    await page.emulateMedia({ colorScheme })
    const post = await openPost(page, corpus, POSTS.reader, 'tag=pager')
    const body = pane(page).locator('.post-body')
    await expect(body.getByRole('heading', { name: 'A complete reading page' })).toBeVisible()
    await expect(body.getByRole('heading', { name: 'A complete reading page' })).toHaveCSS(
      'font-size',
      '19.5px',
    )
    await expect(body.getByRole('heading', { name: 'A complete reading page' })).toHaveCSS(
      'font-weight',
      '650',
    )
    await expect(body.locator('p').first()).toHaveCSS('margin-bottom', '12.75px')
    await expect(body.getByRole('link', { name: 'External reference' })).toHaveCSS(
      'text-decoration-line',
      'underline',
    )
    await expect(pane(page).locator('header time')).toHaveText('1 Nov 2026')
    await expect(pane(page).getByRole('link', { name: 'Boosty', exact: true })).toHaveAttribute(
      'href',
      post.boosty_url,
    )
    await expect(body.locator('img, audio, video')).toHaveCount(5)
    expect(
      await body
        .locator('img, audio, video')
        .evaluateAll((nodes) => nodes.map((node) => node.tagName)),
    ).toEqual(['IMG', 'AUDIO', 'IMG', 'VIDEO', 'IMG'])
    await expect(body.locator('.removed-media')).toContainText('Retained glossary')
    await expect(body).toContainText('File not downloaded: missing.txt')
    await expect(body.getByRole('link', { name: 'External reference' })).toHaveAttribute(
      'target',
      '_blank',
    )
    await expect(body.getByRole('link', { name: 'External reference' })).toHaveAttribute(
      'rel',
      /noreferrer/,
    )
    await expect
      .poll(() =>
        body
          .locator('img')
          .evaluateAll((images) =>
            images.every(
              (image) =>
                (image as HTMLImageElement).complete &&
                (image as HTMLImageElement).naturalWidth > 0,
            ),
          ),
      )
      .toBe(true)
    await expect(pane(page)).toHaveCSS('container-name', 'main')
    const pager = pane(page).getByRole('navigation', { name: 'Post navigation' })
    const bounds = await pager.getByRole('link').evaluateAll((links) =>
      links.map((link) => ({
        x: link.getBoundingClientRect().x,
        y: link.getBoundingClientRect().y,
      })),
    )
    expect(bounds).toHaveLength(2)
    const previousBounds = requireFixture(bounds[0])
    const nextBounds = requireFixture(bounds[1])
    expect(Math.abs(previousBounds.y - nextBounds.y)).toBeLessThan(1)
    expect(nextBounds.x).toBeGreaterThan(previousBounds.x)
    expect((await detail(page, corpus, POSTS.reader)).seen).toBe(false)
    await pane(page).evaluate((element) => {
      element.scrollTop = 0
    })
    await info.attach(`reader-${colorScheme}`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
    await body.getByRole('link', { name: 'Another saved post' }).click()
    await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText('Earlier tied post')
    expect(new URL(page.url()).searchParams.get('tag')).toBe('pair')
    expect(new URL(page.url()).hash).toBe('#chapter')
  })

  test(`${colorScheme}: the reading page stays inside a narrow pane`, async ({
    page,
    corpus,
  }, info) => {
    await page.setViewportSize({ width: 390, height: 1000 })
    await page.emulateMedia({ colorScheme })
    await openPost(page, corpus, POSTS.reader, 'tag=pager')
    await expect
      .poll(() =>
        pane(page)
          .locator('img')
          .evaluateAll((images) =>
            images.every(
              (image) =>
                (image as HTMLImageElement).complete &&
                (image as HTMLImageElement).naturalWidth > 0,
            ),
          ),
      )
      .toBe(true)
    expect(await pane(page).evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
      true,
    )
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const links = pane(page).getByRole('navigation', { name: 'Post navigation' }).getByRole('link')
    const bounds = await links.evaluateAll((elements) =>
      elements.map((element) => ({
        x: element.getBoundingClientRect().x,
        y: element.getBoundingClientRect().y,
      })),
    )
    expect(bounds).toHaveLength(2)
    const previousBounds = requireFixture(bounds[0])
    const nextBounds = requireFixture(bounds[1])
    expect(Math.abs(previousBounds.x - nextBounds.x)).toBeLessThan(1)
    expect(nextBounds.y).toBeGreaterThan(previousBounds.y)
    await info.attach(`reader-mobile-${colorScheme}`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
  })
}

test('header tags change only the selected tag and preserve the open post', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader, 'q=cafe&order=oldest')
  await pane(page).getByRole('button', { name: '#pager', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('tag')).toBe('pager')
  expect(new URL(page.url()).searchParams.get('q')).toBe('cafe')
  expect(new URL(page.url()).searchParams.get('order')).toBe('oldest')
  expect(new URL(page.url()).pathname).toBe(postPath(POSTS.reader))
  await expect(sidebar(page).locator('[data-post-id]')).toHaveCount(3)
  await expect(pane(page).getByRole('button', { name: '#pager', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await pane(page).getByRole('button', { name: '#pager', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.has('tag')).toBe(false)
  expect(new URL(page.url()).searchParams.get('q')).toBe('cafe')
})

for (const order of ['newest', 'oldest']) {
  for (const excluded of [false, true]) {
    test(`${order} pager uses tied IDs with current post ${excluded ? 'excluded' : 'included'}`, async ({
      page,
      corpus,
    }) => {
      const search = new URLSearchParams({
        tag: excluded ? 'pair' : 'pager',
        order,
        q: 'cafe',
      }).toString()
      const posts = await list(page, corpus, search)
      const expectedIds: string[] = [POSTS.before]
      if (!excluded) expectedIds.push(POSTS.reader)
      expectedIds.push(POSTS.after)
      if (order === 'newest') expectedIds.reverse()
      expect(posts.rows.map((post) => post.id)).toEqual(expectedIds)
      await openPost(page, corpus, POSTS.reader, search)
      const pager = pane(page).getByRole('navigation', { name: 'Post navigation' })
      const previous = requireFixture(posts.rows[0])
      const next = posts.rows.at(-1)!
      await expect(
        pager.getByRole('link', { name: `Previous: ${previous.title}` }),
      ).toHaveAttribute('href', new RegExp(`/p/${previous.id}\\?`))
      const nextLink = pager.getByRole('link', { name: `Next: ${next.title}` })
      const href = new URL((await nextLink.getAttribute('href'))!, corpus.origin)
      expect(href.searchParams.get('tag')).toBe(excluded ? 'pair' : 'pager')
      expect(href.searchParams.get('q')).toBe('cafe')
      expect(href.searchParams.get('order')).toBe(order === 'oldest' ? 'oldest' : null)
      await nextLink.click()
      await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText(next.title)
      await expect(pane(page).getByRole('link', { name: /^Next:/ })).toHaveCount(0)
      await page.goBack()
      await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText('Complete saved post')
    })
  }
}

test('new filters disable stale pager links until their real response arrives', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader, 'tag=pager')
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`**${API_PATH}/posts?*`, async (route) => {
    if (new URL(route.request().url()).searchParams.get('tag') === 'reading') await gate
    await route.continue()
  })
  try {
    await pane(page).getByRole('button', { name: '#reading', exact: true }).click()
    await expect(pane(page).getByRole('status')).toHaveText('Updating post navigation...')
    await expect(pane(page).getByRole('navigation', { name: 'Post navigation' })).toHaveCount(0)
  } finally {
    release()
  }
  await expect(sidebar(page).locator('[data-post-id]')).toHaveCount(1)
  await expect(pane(page).getByRole('status')).toHaveCount(0)
})

test('body search walks two hits, folds text correctly and preserves a playing element', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader, 'tag=reading&order=oldest')
  const audio = pane(page).locator('audio')
  await readyPlayer(audio)
  const handle = await audio.elementHandle()
  await audio.evaluate(async (media: HTMLMediaElement) => {
    media.muted = true
    media.currentTime = 2
    await media.play()
  })
  const search = sidebar(page).getByRole('textbox', { name: 'Search posts' })
  await search.fill('needle')
  await expect(pane(page).getByText('Match 1 of 2 in the text')).toBeVisible()
  await pane(page).getByRole('button', { name: 'Next match', exact: true }).click()
  await expect(pane(page).getByText('Match 2 of 2 in the text')).toBeVisible()
  await expect(pane(page).locator('mark[data-current]')).toHaveText('needle')
  const searches = [
    { query: 'cafe', matches: ['café'] },
    { query: 'елка', matches: ['ёлка'] },
    { query: 'йо', matches: ['йога'] },
    { query: 'ио', matches: [] },
    { query: 'removed', matches: [] },
    { query: 'retained', matches: ['Retained'] },
  ]
  for (const { query, matches } of searches) {
    await search.fill(query)
    await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe(query)
    await expect(pane(page).locator('.post-body mark')).toHaveText(matches)
    await expect(pane(page).locator('[data-page-generated] mark')).toHaveCount(0)
  }
  expect(
    await handle!.evaluate((element) => element === document.querySelector('.post-body audio')),
  ).toBe(true)
  expect(
    await audio.evaluate((media: HTMLMediaElement) => !media.paused && media.currentTime > 2),
  ).toBe(true)
  await pane(page).getByRole('button', { name: 'Clear search in this post' }).click()
  await expect(pane(page).getByRole('search', { name: 'Search in this post' })).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get('tag')).toBe('reading')
  expect(new URL(page.url()).searchParams.get('order')).toBe('oldest')
  await expect(pane(page).locator('.post-body mark')).toHaveCount(0)
  await audio.evaluate((media: HTMLMediaElement) => media.pause())
})

test('body images open full screen, follow authored order and restore opening focus', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.reader)
  const images = pane(page).locator('.post-body img')
  const sources = await images.evaluateAll((nodes) =>
    nodes.map((node) => (node as HTMLImageElement).src),
  )
  expect(sources).toHaveLength(3)
  await images.first().focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Post image viewer' })
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('img')).toHaveAttribute('src', requireFixture(sources[0]))
  await page.keyboard.press('ArrowRight')
  await expect(dialog.locator('img')).toHaveAttribute('src', requireFixture(sources[1]))
  await dialog.getByRole('button', { name: 'Next image' }).click()
  await expect(dialog.locator('img')).toHaveAttribute('src', requireFixture(sources[2]))
  await expect(dialog.getByRole('button', { name: 'Next image' })).toHaveCount(0)
  await page.keyboard.press('ArrowLeft')
  await expect(dialog.locator('img')).toHaveAttribute('src', requireFixture(sources[1]))
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(images.first()).toBeFocused()
})

test('locked retained content remains readable and playable while never-saved content has a locked card', async ({
  page,
  corpus,
}) => {
  await openPost(page, corpus, POSTS.retained)
  await expect(pane(page)).toContainText('Previously saved content remains available below.')
  await expect(pane(page).locator('.post-body')).toContainText('A complete reading page')
  await expect(pane(page).getByRole('button', { name: /favorites/ })).toHaveCount(0)
  const video = pane(page).locator('video')
  await readyPlayer(video)
  await expect
    .poll(() => video.evaluate((media: HTMLMediaElement) => media.currentTime))
    .toBeCloseTo(5, 1)
  await video.evaluate(async (media: HTMLMediaElement) => {
    media.muted = true
    await media.play()
  })
  await expect
    .poll(() => video.evaluate((media: HTMLMediaElement) => media.currentTime))
    .toBeGreaterThan(5.1)
  await video.evaluate((media: HTMLMediaElement) => media.pause())
  await openPost(page, corpus, POSTS.locked)
  await expect(pane(page).getByRole('region', { name: 'Locked post' })).toBeVisible()
  await expect(pane(page)).toContainText('Subscription price: 300 ₽ / month')
  await expect(pane(page)).toContainText('Post price: 500 ₽')
  await expect(pane(page).locator('.post-body')).toHaveCount(0)
  await expect(pane(page).getByRole('button', { name: /favorites/ })).toHaveCount(0)
})

test('favorite success persists, refreshes filtered rows and counts, and failure rolls back', async ({
  page,
  corpus,
}) => {
  const initial = await author(page, corpus)
  await openPost(page, corpus, POSTS.favorite, 'fav=1')
  await expect(sidebar(page).locator('[data-post-id]')).toHaveCount(0)
  await pane(page).getByRole('button', { name: 'Add to favorites' }).click()
  await expect(pane(page).getByRole('button', { name: 'Remove from favorites' })).toBeEnabled()
  await expect(sidebar(page).locator(`[data-post-id="${POSTS.favorite}"]`)).toBeVisible()
  await expect(sidebar(page)).toContainText(`${initial.favorites + 1} favorites`)
  expect((await author(page, corpus)).favorites).toBe(initial.favorites + 1)
  await page.reload()
  await expect(pane(page).getByRole('button', { name: 'Remove from favorites' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(pane(page).locator('.post-body')).toContainText('A complete reading page')
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`**${API_PATH}/posts/${POSTS.favorite}/marks`, async (route) => {
    await gate
    await route.fulfill({
      status: 503,
      json: {
        error: { code: 'temporary_failure', message: 'Favorite update refused for the test.' },
      },
    })
  })
  try {
    await pane(page).getByRole('button', { name: 'Remove from favorites' }).click()
    await expect(pane(page).getByRole('button', { name: 'Add to favorites' })).toBeDisabled()
    await expect(sidebar(page).locator('[data-post-id]')).toHaveCount(0)
    await expect(sidebar(page)).not.toContainText(`${initial.favorites + 1} favorites`)
  } finally {
    release()
  }
  await expect(pane(page).getByRole('alert')).toHaveText('Favorite update refused for the test.')
  await expect(pane(page).getByRole('button', { name: 'Remove from favorites' })).toBeEnabled()
  await expect(sidebar(page).locator(`[data-post-id="${POSTS.favorite}"]`)).toBeVisible()
  await expect(sidebar(page)).toContainText(`${initial.favorites + 1} favorites`)
  expect((await detail(page, corpus, POSTS.favorite)).favorite).toBe(true)
  await page.unroute(`**${API_PATH}/posts/${POSTS.favorite}/marks`)
  await pane(page).getByRole('button', { name: 'Remove from favorites' }).click()
  await expect(pane(page).getByRole('button', { name: 'Add to favorites' })).toBeEnabled()
  await expect(sidebar(page).locator('[data-post-id]')).toHaveCount(0)
  expect((await author(page, corpus)).favorites).toBe(initial.favorites)
})
