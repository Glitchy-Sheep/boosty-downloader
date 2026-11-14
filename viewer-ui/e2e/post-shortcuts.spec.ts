import type { Locator, Page } from '@playwright/test'

import type { PostList, PostRow } from '../src/lib/api.gen'
import {
  POSTS,
  expect,
  list,
  openPost,
  pane,
  postPath,
  readyPlayer,
  test,
  type PostCorpus,
} from './post-fixtures'
import { requireFixture } from './required-fixture'

const AUTHOR = 'shortcut_checks'
const SHORTCUT_API = `/api/authors/${AUTHOR}`
type PhysicalKey = { code: 'KeyJ' | 'KeyK' | 'Slash'; key: string }
const NEXT: PhysicalKey = { code: 'KeyJ', key: 'j' }
const PREVIOUS: PhysicalKey = { code: 'KeyK', key: 'k' }
const SEARCH: PhysicalKey = { code: 'Slash', key: '/' }

function shortcutPath(id: string): string {
  return `/a/${AUTHOR}/p/${id}`
}

function shortcutSidebar(page: Page): Locator {
  return page.getByRole('complementary', { name: 'Posts of Shortcut Checks' })
}

async function shortcutPosts(page: Page, corpus: PostCorpus, search = ''): Promise<PostRow[]> {
  const response = await page.request.get(`${corpus.origin}${SHORTCUT_API}/posts?${search}`)
  expect(response.ok()).toBe(true)
  const posts = (await response.json()) as PostList
  return posts.rows
}

async function blurControl(page: Page): Promise<void> {
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  })
}

/** Dispatch one synchronous burst to test key positions independently of the OS layout. */
async function burst(page: Page, key: PhysicalKey, count = 1): Promise<void> {
  await page.evaluate(
    ({ code, key: value, count: presses }) => {
      for (let index = 0; index < presses; index++) {
        document.body.dispatchEvent(
          new KeyboardEvent('keydown', {
            code,
            key: value,
            bubbles: true,
            cancelable: true,
            repeat: index > 0,
          }),
        )
      }
    },
    { ...key, count },
  )
}

async function expectShortcutPost(page: Page, post: PostRow, search = ''): Promise<void> {
  await expect(page).toHaveURL((url) => url.pathname === shortcutPath(post.id))
  await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText(post.title)
  const current = shortcutSidebar(page).locator(`[data-post-id="${post.id}"]`)
  await expect(current).toHaveAttribute('aria-current', 'page')
  await expect(current).toBeInViewport()
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual(
    Object.fromEntries(new URLSearchParams(search)),
  )
}

async function openShortcut(page: Page, corpus: PostCorpus, post: PostRow, search = '') {
  await page.goto(`${corpus.origin}${shortcutPath(post.id)}${search ? `?${search}` : ''}`)
  await expectShortcutPost(page, post, search)
  await expect(shortcutSidebar(page).getByLabel('Updating posts')).toHaveCount(0)
}

for (const layout of [
  { name: 'English', next: 'j', previous: 'k' },
  { name: 'Russian', next: 'о', previous: 'л' },
]) {
  for (const order of ['newest', 'oldest'] as const) {
    test(`${layout.name} physical keys retain ten fast moves in ${order} order and preserve filters`, async ({
      page,
      corpus,
    }) => {
      const search = new URLSearchParams({
        q: 'shortcut',
        tag: 'keyboard',
        unseen: '1',
        fav: '1',
        ...(order === 'oldest' ? { order } : {}),
      }).toString()
      const posts = await shortcutPosts(page, corpus, search)
      expect(posts).toHaveLength(12)
      const first = requireFixture(posts[0])
      const tenth = requireFixture(posts[10])
      await openShortcut(page, corpus, first, search)

      await burst(page, { code: 'KeyJ', key: layout.next }, 10)
      await expectShortcutPost(page, tenth, search)
      await burst(page, { code: 'KeyK', key: layout.previous }, 10)
      await expectShortcutPost(page, first, search)
    })
  }
}

test('real keys respect boundaries and Slash focuses and selects the current search', async ({
  page,
  corpus,
}) => {
  const search = 'q=shortcut&tag=keyboard'
  const posts = await shortcutPosts(page, corpus, search)
  const first = requireFixture(posts[0])
  const second = requireFixture(posts[1])
  const last = requireFixture(posts.at(-1))
  await openShortcut(page, corpus, first, search)
  await page.keyboard.press('k')
  await expectShortcutPost(page, first, search)
  await page.keyboard.press('j')
  await expectShortcutPost(page, second, search)
  await burst(page, NEXT, 30)
  await expectShortcutPost(page, last, search)
  await page.keyboard.press('j')
  await expectShortcutPost(page, last, search)

  await page.keyboard.press('/')
  const input = shortcutSidebar(page).getByRole('textbox', { name: 'Search posts' })
  await expect(input).toBeFocused()
  expect(
    await input.evaluate((element: HTMLInputElement) => ({
      start: element.selectionStart,
      end: element.selectionEnd,
      value: element.value,
    })),
  ).toEqual({ start: 0, end: 8, value: 'shortcut' })
  await page.keyboard.type('jk/')
  await expect(input).toHaveValue('jk/')
  await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('jk/')
  expect(new URL(page.url()).pathname).toBe(shortcutPath(last.id))
})

for (const order of ['newest', 'oldest'] as const) {
  test(`${order} keyboard navigation handles a filtered-out open post and media filters`, async ({
    page,
    corpus,
  }) => {
    const search = new URLSearchParams({
      tag: 'pair',
      kind: 'videos',
      incomplete: '1',
      unseen: '1',
      q: 'cafe',
      ...(order === 'oldest' ? { order } : {}),
    }).toString()
    const posts = await list(page, corpus, search)
    expect(posts.rows).toHaveLength(2)
    const previous = requireFixture(posts.rows[0])
    const next = requireFixture(posts.rows[1])
    await openPost(page, corpus, POSTS.reader, search)
    await expect(pane(page).getByRole('navigation', { name: 'Post navigation' })).toBeVisible()
    await page.keyboard.press('j')
    await expect(page).toHaveURL((url) => url.pathname === postPath(next.id))
    await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText(next.title)
    await page.keyboard.press('k')
    await expect(page).toHaveURL((url) => url.pathname === postPath(previous.id))
    expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual(
      Object.fromEntries(new URLSearchParams(search)),
    )
  })
}

test('filter changes and browser history supply the next keyboard selection', async ({
  page,
  corpus,
}) => {
  const search = 'tag=keyboard&order=oldest'
  const posts = await shortcutPosts(page, corpus, search)
  const first = requireFixture(posts[0])
  const second = requireFixture(posts[1])
  const third = requireFixture(posts[2])
  await openShortcut(page, corpus, first, search)
  const tag = shortcutSidebar(page).getByRole('combobox', { name: 'Tag', exact: true })
  await tag.selectOption('even')
  await expect(shortcutSidebar(page).locator('[data-post-id]')).toHaveCount(6)
  await blurControl(page)
  await page.keyboard.press('j')
  await expectShortcutPost(page, third, 'tag=even&order=oldest')
  await page.goBack()
  await expectShortcutPost(page, first, 'tag=even&order=oldest')
  await page.goBack()
  await expectShortcutPost(page, first, search)
  await page.keyboard.press('j')
  await expectShortcutPost(page, second, search)
  await page.goBack()
  await expectShortcutPost(page, first, search)
  await page.goForward()
  await expectShortcutPost(page, second, search)
  await page.keyboard.press('j')
  await expectShortcutPost(page, third, search)
})

test('locked and media-kind filters remain active when keyboard navigation opens a locked card', async ({
  page,
  corpus,
}) => {
  const search = 'tag=locked&kind=videos&locked=1'
  const posts = await list(page, corpus, search)
  expect(posts.rows.map((post) => post.id)).toEqual([POSTS.retained, POSTS.locked])
  await openPost(page, corpus, POSTS.retained, search)
  await expect(pane(page).getByRole('navigation', { name: 'Post navigation' })).toBeVisible()
  await page.keyboard.press('j')
  await expect(page).toHaveURL((url) => url.pathname === postPath(POSTS.locked))
  await expect(pane(page).getByRole('region', { name: 'Locked post' })).toBeVisible()
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual(
    Object.fromEntries(new URLSearchParams(search)),
  )
  await page.keyboard.press('k')
  await expect(page).toHaveURL((url) => url.pathname === postPath(POSTS.retained))
})

test('pending or failed filtered lists reject stale navigation while search stays available', async ({
  page,
  corpus,
}) => {
  const posts = await shortcutPosts(page, corpus)
  const current = requireFixture(posts[5])
  const next = requireFixture(posts[6])
  await openShortcut(page, corpus, current)
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`**${SHORTCUT_API}/posts?*`, async (route) => {
    if (new URL(route.request().url()).searchParams.get('tag') !== 'odd') {
      await route.continue()
      return
    }
    await gate
    await route.fulfill({
      status: 503,
      json: { error: { code: 'temporary_failure', message: 'Shortcut list unavailable.' } },
    })
  })
  try {
    await shortcutSidebar(page)
      .getByRole('combobox', { name: 'Tag', exact: true })
      .selectOption('odd')
    await expect(pane(page).getByRole('status')).toHaveText('Updating post navigation...')
    await blurControl(page)
    await burst(page, NEXT, 3)
    expect(new URL(page.url()).pathname).toBe(shortcutPath(current.id))
    await page.keyboard.press('/')
    await expect(shortcutSidebar(page).getByRole('textbox', { name: 'Search posts' })).toBeFocused()
  } finally {
    release()
  }
  await expect(shortcutSidebar(page).getByRole('alert')).toHaveText('Shortcut list unavailable.')
  await blurControl(page)
  await burst(page, NEXT, 3)
  expect(new URL(page.url()).pathname).toBe(shortcutPath(current.id))
  await page.keyboard.press('/')
  await expect(shortcutSidebar(page).getByRole('textbox', { name: 'Search posts' })).toBeFocused()
  await page.unroute(`**${SHORTCUT_API}/posts?*`)
  await shortcutSidebar(page).getByRole('button', { name: 'Retry posts' }).click()
  await expect(shortcutSidebar(page).getByRole('alert')).toHaveCount(0)
  await expect(shortcutSidebar(page).locator('[data-post-id]')).toHaveCount(6)
  await page.keyboard.press('j')
  await expectShortcutPost(page, next, 'tag=odd')
})

test('modifiers, composition, prevented events and form controls retain their keyboard input', async ({
  page,
  corpus,
}) => {
  const posts = await shortcutPosts(page, corpus)
  const current = requireFixture(posts[5])
  await openShortcut(page, corpus, current)
  const prevented = await page.evaluate(() => {
    const guarded: KeyboardEventInit[] = [
      { ctrlKey: true },
      { altKey: true },
      { metaKey: true },
      { shiftKey: true },
      { isComposing: true },
    ]
    return guarded.map((guard) => {
      const event = new KeyboardEvent('keydown', {
        key: 'j',
        code: 'KeyJ',
        bubbles: true,
        cancelable: true,
        ...guard,
      })
      document.body.dispatchEvent(event)
      return event.defaultPrevented
    })
  })
  expect(prevented).toEqual([false, false, false, false, false])
  await page.evaluate(() => {
    document.body.addEventListener('keydown', (event) => event.preventDefault(), { once: true })
    document.body.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: 'j',
        code: 'KeyJ',
        bubbles: true,
        cancelable: true,
      }),
    )
  })
  await expectShortcutPost(page, current)
  const sort = shortcutSidebar(page).getByRole('combobox', { name: 'Sort order' })
  await sort.focus()
  await page.keyboard.press('j')
  await expectShortcutPost(page, current)
  await pane(page).getByRole('button', { name: 'Remove from favorites' }).focus()
  await page.keyboard.press('j')
  await expectShortcutPost(page, requireFixture(posts[6]))
})

test('native players and the image dialog keep their own keys', async ({ page, corpus }) => {
  await openPost(page, corpus, POSTS.reader, 'tag=pager')
  await expect(pane(page).getByRole('navigation', { name: 'Post navigation' })).toBeVisible()
  for (const kind of ['audio', 'video']) {
    const player = pane(page).locator(kind)
    await readyPlayer(player)
    const original = requireFixture(await player.elementHandle())
    for (const key of ['j', 'k', '/']) {
      await player.focus()
      await expect(player).toBeFocused()
      await page.keyboard.press(key)
      expect(new URL(page.url()).pathname, `${kind} retains ${key}`).toBe(postPath(POSTS.reader))
      expect(
        await original.evaluate(
          (element, tag) =>
            element.isConnected && element === document.querySelector(`.post-body ${tag}`),
          kind,
        ),
      ).toBe(true)
      await expect(page.getByRole('textbox', { name: 'Search posts' })).not.toBeFocused()
    }
  }
  const image = pane(page).locator('.post-body img').first()
  await image.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Post image viewer' })
  await expect(dialog).toBeVisible()
  for (const key of [NEXT, PREVIOUS, SEARCH]) await burst(page, key)
  expect(new URL(page.url()).pathname).toBe(postPath(POSTS.reader))
  await expect(dialog).toBeVisible()
  await expect(
    page.getByRole('textbox', { name: 'Search posts', includeHidden: true }),
  ).not.toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('leaving Posts removes shortcut handling from the authors page', async ({ page, corpus }) => {
  const posts = await shortcutPosts(page, corpus)
  await openShortcut(page, corpus, requireFixture(posts[0]))
  await page.getByRole('link', { name: 'Authors', exact: true }).click()
  await expect(page).toHaveURL(`${corpus.origin}/`)
  await expect(page.getByRole('heading', { name: 'Authors', exact: true })).toBeVisible()
  for (const key of [NEXT, PREVIOUS, SEARCH]) await burst(page, key)
  await expect(page).toHaveURL(`${corpus.origin}/`)
  await expect(page.getByRole('textbox', { name: 'Search posts' })).toHaveCount(0)
})
