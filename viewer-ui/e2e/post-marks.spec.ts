import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'

import type { Locator, Page } from '@playwright/test'

import type {
  Author,
  BulkMarksProgressResponse,
  BulkMarksRequest,
  PostDetail,
  PostList,
} from '../src/lib/api.gen'
import { expect, test } from './marks-fixtures'
import { pane, type PostCorpus } from './post-fixtures'
import { openMobileSidebar } from './mobile-sidebar-fixtures'
import { requireFixture } from './required-fixture'

const AUTHOR = 'marks_checks'
const API = `/api/authors/${AUTHOR}`
const POST = {
  unseen: '30000000-0000-4000-8000-000000000001',
  updated: '30000000-0000-4000-8000-000000000002',
  seen: '30000000-0000-4000-8000-000000000003',
  another: '30000000-0000-4000-8000-000000000004',
  locked: '30000000-0000-4000-8000-000000000005',
  unopened: '30000000-0000-4000-8000-000000000006',
  favorite: '30000000-0000-4000-8000-000000000007',
  playback: '30000000-0000-4000-8000-000000000012',
} as const

type MarkAction = 'seen' | 'favorite'
type PhysicalKey = { code: 'KeyJ' | 'KeyS' | 'KeyF'; key: string }
type Gate = { promise: Promise<void>; release: () => void }
const LABELS: Record<MarkAction, { enable: string; disable: string }> = {
  seen: { enable: 'Mark as seen', disable: 'Mark as unseen' },
  favorite: { enable: 'Add to favorites', disable: 'Remove from favorites' },
}

function gate(): Gate {
  let release = (): void => {}
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

function sidebar(page: Page): Locator {
  return page.getByRole('complementary', { name: 'Posts of Marks Checks' })
}

function row(page: Page, id: string): Locator {
  return sidebar(page).locator(`[data-post-row="${id}"]`)
}

function postPath(id: string): string {
  return `/a/${AUTHOR}/p/${id}`
}

function markButton(page: Page, action: MarkAction, current: boolean): Locator {
  const labels = LABELS[action]
  return pane(page).getByRole('button', { name: current ? labels.disable : labels.enable })
}

async function detail(page: Page, marks: PostCorpus, id: string): Promise<PostDetail> {
  const response = await page.request.get(`${marks.origin}${API}/posts/${id}`)
  expect(response.ok()).toBe(true)
  return (await response.json()) as PostDetail
}

async function list(page: Page, marks: PostCorpus, search = ''): Promise<PostList> {
  const response = await page.request.get(`${marks.origin}${API}/posts?${search}`)
  expect(response.ok()).toBe(true)
  return (await response.json()) as PostList
}

async function author(page: Page, marks: PostCorpus): Promise<Author> {
  const response = await page.request.get(`${marks.origin}${API}`)
  expect(response.ok()).toBe(true)
  return (await response.json()) as Author
}

async function openPost(page: Page, marks: PostCorpus, id: string, search = '') {
  await page.goto(`${marks.origin}${postPath(id)}${search ? `?${search}` : ''}`)
  await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText(
    (await detail(page, marks, id)).title,
  )
  await expect(sidebar(page).getByLabel('Updating posts')).toHaveCount(0)
}

async function storedMarks(marks: PostCorpus): Promise<Record<string, string>> {
  const root = path.join(marks.library, AUTHOR)
  const names = (await readdir(root, { recursive: true }))
    .filter((name) => path.basename(name) === 'viewer.json')
    .sort()
  expect(names).toHaveLength(12)
  const values: Record<string, string> = {}
  for (const name of names) values[name] = await readFile(path.join(root, name), 'utf8')
  return values
}

async function physicalKeys(page: Page, keys: PhysicalKey[]): Promise<void> {
  await page.evaluate((presses) => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    for (const key of presses)
      document.body.dispatchEvent(
        new KeyboardEvent('keydown', { ...key, bubbles: true, cancelable: true }),
      )
  }, keys)
}

async function bulkConfirmation(page: Page, seen: boolean, count: number): Promise<Locator> {
  await sidebar(page).getByRole('button', { name: 'Mark posts', exact: true }).click()
  const state = seen ? 'seen' : 'unseen'
  await page.getByRole('menuitem', { name: `Mark all as ${state}`, exact: true }).click()
  const noun = count === 1 ? 'post' : 'posts'
  const dialog = page.getByRole('dialog', { name: `Mark ${count} ${noun} as ${state}?` })
  await expect(dialog).toBeVisible()
  return dialog
}

test('canonical marks distinguish updated posts and opening or browsing does not change them', async ({
  page,
  marks,
}) => {
  expect(await author(page, marks)).toMatchObject({ posts: 13, locked: 1, unseen: 8, favorites: 2 })
  expect(await detail(page, marks, POST.updated)).toMatchObject({ seen: true, updated: true })
  expect((await list(page, marks, 'tag=stream&unseen=1')).rows.map((post) => post.id)).toEqual([
    POST.unseen,
    POST.updated,
    POST.another,
  ])
  const before = await storedMarks(marks)
  await openPost(page, marks, POST.unseen, 'tag=keyboard')
  await page.keyboard.press('j')
  await expect(page).toHaveURL((url) => url.pathname === postPath(POST.updated))
  await expect(markButton(page, 'seen', false)).toBeVisible()
  await expect(pane(page).getByText('Updated', { exact: true })).toBeVisible()
  await expect(row(page, POST.updated).getByText('Updated', { exact: true })).toBeVisible()
  await expect(row(page, POST.updated).getByRole('link')).toHaveAccessibleDescription(/Unseen/)
  await openPost(page, marks, POST.locked, 'tag=stream')
  await expect(pane(page).getByRole('button', { name: /Mark as|favorites/ })).toHaveCount(0)
  await expect(row(page, POST.locked).getByRole('button')).toHaveCount(0)
  await physicalKeys(page, [
    { code: 'KeyS', key: 's' },
    { code: 'KeyF', key: 'f' },
  ])
  expect(await storedMarks(marks)).toEqual(before)
})

for (const layout of [
  { name: 'English', next: 'j', seen: 's', favorite: 'f' },
  { name: 'Russian', next: 'о', seen: 'ы', favorite: 'а' },
]) {
  for (const action of ['seen', 'favorite'] as const) {
    test(`${layout.name}: immediate J then ${action} marks the newly chosen post`, async ({
      page,
      marks,
    }) => {
      await openPost(page, marks, POST.unseen, 'tag=keyboard')
      const writes: string[] = []
      page.on('request', (request) => {
        if (request.method() === 'PUT' && request.url().endsWith('/marks'))
          writes.push(request.url())
      })
      const key: PhysicalKey = { code: action === 'seen' ? 'KeyS' : 'KeyF', key: layout[action] }
      await physicalKeys(page, [{ code: 'KeyJ', key: layout.next }, key])
      await expect(page).toHaveURL((url) => url.pathname === postPath(POST.updated))
      await expect(markButton(page, action, true)).toBeEnabled()
      await expect.poll(async () => (await detail(page, marks, POST.updated))[action]).toBe(true)
      expect(writes).toEqual([`${marks.origin}${API}/posts/${POST.updated}/marks`])
      expect(await detail(page, marks, POST.unseen)).toMatchObject({ seen: false, favorite: false })
      if (action === 'seen') {
        await expect(pane(page).getByText('Updated', { exact: true })).toHaveCount(0)
        expect((await detail(page, marks, POST.updated)).updated).toBe(false)
      }
      await page.reload()
      await expect(markButton(page, action, true)).toBeEnabled()
    })
  }
}

test('seen changes optimistically remove a filtered row and refresh both author counters', async ({
  page,
  marks,
}, info) => {
  await openPost(page, marks, POST.unseen, 'tag=stream&unseen=1')
  const address = page.url()
  const held = gate()
  await page.route(`**${API}/posts/${POST.unseen}/marks`, async (route) => {
    await held.promise
    await route.continue()
  })
  try {
    await markButton(page, 'seen', false).click()
    await expect(markButton(page, 'seen', true)).toBeDisabled()
    await expect(row(page, POST.unseen)).toHaveCount(0)
    await expect(sidebar(page).getByText('7 unseen', { exact: true })).toBeVisible()
    await expect(sidebar(page).getByText('2 posts', { exact: true })).toBeVisible()
    expect((await detail(page, marks, POST.unseen)).seen).toBe(false)
    await expect(page).toHaveURL(address)
  } finally {
    held.release()
  }
  await expect(markButton(page, 'seen', true)).toBeEnabled()
  expect((await detail(page, marks, POST.unseen)).seen).toBe(true)
  await page.reload()
  await expect(markButton(page, 'seen', true)).toBeEnabled()
  await expect(row(page, POST.unseen)).toHaveCount(0)
  await info.attach('seen-filtered-row', {
    body: await page.screenshot(),
    contentType: 'image/png',
  })
  await page.getByRole('link', { name: 'Authors', exact: true }).click()
  await expect(
    page.getByRole('link', { name: 'Marks Checks', exact: true }),
  ).toHaveAccessibleDescription(/7 unseen/)
})

test('failed updated acknowledgement restores its badge, filtered row and unread count', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.updated, 'tag=stream&unseen=1')
  const held = gate()
  await page.route(`**${API}/posts/${POST.updated}/marks`, async (route) => {
    await held.promise
    await route.fulfill({
      status: 503,
      json: { error: { code: 'temporary_failure', message: 'Seen update refused.' } },
    })
  })
  try {
    await markButton(page, 'seen', false).click()
    await expect(row(page, POST.updated)).toHaveCount(0)
    await expect(pane(page).getByText('Updated', { exact: true })).toHaveCount(0)
    await expect(sidebar(page).getByText('7 unseen', { exact: true })).toBeVisible()
  } finally {
    held.release()
  }
  await expect(pane(page).getByRole('alert')).toContainText('Seen update refused.')
  await expect(markButton(page, 'seen', false)).toBeEnabled()
  await expect(row(page, POST.updated).getByText('Updated', { exact: true })).toBeVisible()
  await expect(sidebar(page).getByText('8 unseen', { exact: true })).toBeVisible()
  expect(await detail(page, marks, POST.updated)).toMatchObject({ seen: true, updated: true })
  await page.unroute(`**${API}/posts/${POST.updated}/marks`)
  await markButton(page, 'seen', false).click()
  await expect(markButton(page, 'seen', true)).toBeEnabled()
  await expect(pane(page).getByText('Updated', { exact: true })).toHaveCount(0)
})

test('an unopened row heart uses its listing and keeps the current page while keyboard reachable', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.unseen, 'tag=notes')
  const address = page.url()
  const detailRequests: string[] = []
  page.on('request', (request) => {
    if (request.url() === `${marks.origin}${API}/posts/${POST.unopened}`)
      detailRequests.push(request.url())
  })
  const target = row(page, POST.unopened)
  const heart = target.getByRole('button', { name: 'Add to favorites' })
  await heart.focus()
  await expect(heart).toHaveCSS('opacity', '1')
  await page.keyboard.press('Enter')
  await expect(target.getByRole('button', { name: 'Remove from favorites' })).toBeEnabled()
  await expect(sidebar(page)).toContainText('3 favorites')
  await expect(page).toHaveURL(address)
  await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText('Unseen stream')
  expect(detailRequests).toEqual([])
  expect((await detail(page, marks, POST.unopened)).favorite).toBe(true)
  await page.reload()
  await expect(
    row(page, POST.unopened).getByRole('button', { name: 'Remove from favorites' }),
  ).toBeVisible()
})

test.describe('touch row hearts', () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 1000 } })
  for (const colorScheme of ['light', 'dark'] as const) {
    test(`${colorScheme}: an empty heart is visible and tapping it does not open the row`, async ({
      page,
      marks,
    }, info) => {
      await page.emulateMedia({ colorScheme })
      await openPost(page, marks, POST.unseen, 'tag=notes')
      await openMobileSidebar(page)
      const address = page.url()
      const heart = row(page, POST.unopened).getByRole('button', { name: 'Add to favorites' })
      await expect(heart).toHaveCSS('opacity', '1')
      await expect(heart).not.toHaveCSS('pointer-events', 'none')
      await heart.tap()
      await expect(
        row(page, POST.unopened).getByRole('button', { name: 'Remove from favorites' }),
      ).toBeEnabled()
      await expect(page).toHaveURL(address)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await info.attach(`marks-touch-${colorScheme}`, {
        body: await page.screenshot(),
        contentType: 'image/png',
      })
    })
  }
})

test('removing a row favorite keeps its selected page and updates filtered month choices', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.favorite, 'fav=1')
  const address = page.url()
  await expect(
    sidebar(page).getByRole('combobox', { name: 'Jump to month' }).locator('option'),
  ).toHaveCount(2)
  await row(page, POST.favorite).getByRole('button', { name: 'Remove from favorites' }).click()
  await expect(row(page, POST.favorite)).toHaveCount(0)
  await expect(markButton(page, 'favorite', false)).toBeEnabled()
  await expect(
    sidebar(page).getByRole('combobox', { name: 'Jump to month' }).locator('option'),
  ).toHaveCount(1)
  await expect(sidebar(page)).toContainText('1 favorite')
  await expect(page).toHaveURL(address)
  await expect(pane(page).getByRole('heading', { level: 1 })).toHaveText('Favorite notes')
})

test('explicit marks retain saved playback and a failure after saving rereads canonical state', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.playback, 'tag=notes')
  expect(requireFixture((await detail(page, marks, POST.playback)).media[0]).position_s).toBe(7)
  await page.route(`**${API}/posts/${POST.playback}/marks`, async (route) => {
    const response = await route.fetch()
    expect(response.ok()).toBe(true)
    await route.fulfill({
      status: 500,
      json: { error: { code: 'index_failure', message: 'Saved mark needs index refresh.' } },
    })
  })
  await markButton(page, 'seen', false).click()
  await expect(pane(page).getByRole('alert')).toContainText('Saved mark needs index refresh.')
  await expect(markButton(page, 'seen', true)).toBeEnabled()
  await page.unroute(`**${API}/posts/${POST.playback}/marks`)
  await markButton(page, 'favorite', false).click()
  await expect(markButton(page, 'favorite', true)).toBeEnabled()
  const saved = await detail(page, marks, POST.playback)
  expect(saved).toMatchObject({ seen: true, favorite: true })
  expect(requireFixture(saved.media[0]).position_s).toBe(7)
  await page.reload()
  await expect(markButton(page, 'seen', true)).toBeEnabled()
  await expect(markButton(page, 'favorite', true)).toBeEnabled()
})

test('bulk confirmation counts actual changes and cancelling performs no write', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.unseen, 'tag=stream')
  const before = await storedMarks(marks)
  const writes: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/marks')) writes.push(request.url())
  })
  await (await bulkConfirmation(page, true, 3)).getByRole('button', { name: 'Cancel' }).click()
  await (await bulkConfirmation(page, false, 2)).getByRole('button', { name: 'Cancel' }).click()
  expect(await storedMarks(marks)).toEqual(before)
  expect(writes).toEqual([])
  await openPost(page, marks, POST.locked, 'tag=stream&locked=1')
  await expect(
    sidebar(page).getByRole('button', { name: 'Mark posts', exact: true }),
  ).toBeDisabled()
})

test('bulk progress keeps processed and changed counts distinct and waits for its POST result', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.unseen, 'tag=stream')
  const address = page.url()
  const held = gate()
  let requested: BulkMarksRequest | undefined
  let progress: BulkMarksProgressResponse = { active: true, total: 4, completed: 2, changed: 1 }
  await page.route(`**${API}/marks/progress`, (route) => route.fulfill({ json: progress }))
  await page.route(`**${API}/marks`, async (route) => {
    requested = route.request().postDataJSON() as BulkMarksRequest
    await held.promise
    await route.continue()
  })
  const dialog = await bulkConfirmation(page, true, 3)
  try {
    await dialog.getByRole('button', { name: 'Mark as seen', exact: true }).click()
    const active = page.getByRole('dialog', { name: 'Marking posts', exact: true })
    await expect
      .poll(() =>
        active
          .getByRole('progressbar', { name: 'Marking progress' })
          .evaluate((element: HTMLProgressElement) => ({ value: element.value, max: element.max })),
      )
      .toEqual({ value: 2, max: 4 })
    await expect(active).toContainText('2 of 4 posts processed')
    await expect(active).toContainText('1 post changed')
    expect(requested).toMatchObject({ seen: true, filters: { tag: 'stream', unseen: false } })
    progress = { active: false, total: null, completed: 0, changed: 0 }
    await expect(active).toContainText('Waiting for the marking result...')
    await active.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(
      sidebar(page).getByRole('button', { name: 'Show marking progress', exact: true }),
    ).toBeEnabled()
    await expect(
      sidebar(page).getByRole('button', { name: 'Mark posts', exact: true }),
    ).toHaveCount(0)
    await expect(markButton(page, 'seen', false)).toBeDisabled()
    await expect(sidebar(page)).not.toContainText('Marked 3 posts as seen.')
    expect((await author(page, marks)).unseen).toBe(8)
  } finally {
    held.release()
  }
  await sidebar(page).getByRole('button', { name: 'Mark posts', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Last marking result', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Marked 3 posts as seen.')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(markButton(page, 'seen', true)).toBeEnabled()
  expect(await author(page, marks)).toMatchObject({ unseen: 5, favorites: 2 })
  expect((await list(page, marks, 'tag=stream&unseen=1')).total).toBe(0)
  expect((await detail(page, marks, POST.unopened)).seen).toBe(false)
  await expect(page).toHaveURL(address)
})

test('bulk unseen includes previously updated posts without double-counting the unread total', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.updated, 'tag=stream')
  const dialog = await bulkConfirmation(page, false, 2)
  await dialog.getByRole('button', { name: 'Mark as unseen', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Marked 2 posts as unseen.')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  expect(await author(page, marks)).toMatchObject({ unseen: 9 })
  expect(await detail(page, marks, POST.updated)).toMatchObject({ seen: false, updated: false })
  expect((await list(page, marks, 'tag=stream&unseen=1')).total).toBe(4)
  await page.reload()
  await expect(markButton(page, 'seen', false)).toBeEnabled()
  await expect(sidebar(page).getByText('9 unseen', { exact: true })).toBeVisible()
})

test('partial bulk failure preserves saved changes, refreshes counts and retries the remainder', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.unseen, 'tag=stream')
  await page.route(`**${API}/marks`, async (route) => {
    const saved = await page.request.put(`${marks.origin}${API}/posts/${POST.unseen}/marks`, {
      headers: { Origin: marks.origin },
      data: { seen: true },
    })
    expect(saved.ok()).toBe(true)
    await route.fulfill({
      status: 500,
      json: { error: { code: 'bulk_failure', message: 'Bulk update interrupted.' } },
    })
  })
  const dialog = await bulkConfirmation(page, true, 3)
  await dialog.getByRole('button', { name: 'Mark as seen', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText(
    'Bulk update interrupted.',
  )
  await expect(page.getByRole('dialog')).not.toContainText('Marked 3 posts')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(markButton(page, 'seen', true)).toBeEnabled()
  await expect(sidebar(page).getByText('7 unseen', { exact: true })).toBeVisible()
  expect(await detail(page, marks, POST.updated)).toMatchObject({ seen: true, updated: true })
  await page.unroute(`**${API}/marks`)
  const retry = await bulkConfirmation(page, true, 2)
  await retry.getByRole('button', { name: 'Mark as seen', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Marked 2 posts as seen.')
  expect((await author(page, marks)).unseen).toBe(5)
})

test('a conflicting bulk reports failure without inventing successful changes', async ({
  page,
  marks,
}) => {
  await openPost(page, marks, POST.unseen, 'tag=stream')
  const before = await storedMarks(marks)
  await page.route(`**${API}/marks`, (route) =>
    route.fulfill({
      status: 409,
      json: { error: { code: 'bulk_busy', message: 'Another mark operation is still running.' } },
    }),
  )
  const dialog = await bulkConfirmation(page, true, 3)
  await dialog.getByRole('button', { name: 'Mark as seen', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText(
    'Another mark operation is still running.',
  )
  await expect(page.getByRole('dialog')).not.toContainText('Marked 3 posts')
  expect(await storedMarks(marks)).toEqual(before)
})
