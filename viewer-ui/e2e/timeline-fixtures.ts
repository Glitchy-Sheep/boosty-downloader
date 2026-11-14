import type { Locator, Page } from '@playwright/test'

import type { Author, PostDetail, PostList, PostRow, TagCount } from '../src/lib/api.gen'
import { actualAuthors, expect, origin } from './fixtures'

export const AUTHOR = 'pixel_forge'
export const AUTHOR_PATH = `/a/${AUTHOR}`
export const API_PATH = `/api/authors/${AUTHOR}`

export function postPath(id: string, search = ''): string {
  return `${AUTHOR_PATH}/p/${encodeURIComponent(id)}${search ? `?${search}` : ''}`
}

export function sidebar(page: Page): Locator {
  return page.getByRole('complementary', { name: 'Posts of Pixel Forge' })
}

export function rows(page: Page): Locator {
  return sidebar(page).locator('[data-post-id]')
}

export function row(page: Page, id: string): Locator {
  return sidebar(page).locator(`[data-post-id="${id}"]`)
}

export function pane(page: Page): Locator {
  return page.getByRole('region', { name: 'Selected post', exact: true })
}

export async function actualPosts(page: Page, search = ''): Promise<PostList> {
  const response = await page.request.get(`${origin()}${API_PATH}/posts${search ? `?${search}` : ''}`)
  expect(response.ok()).toBe(true)
  return await response.json() as PostList
}

export async function actualTags(page: Page): Promise<TagCount[]> {
  const response = await page.request.get(`${origin()}${API_PATH}/tags`)
  expect(response.ok()).toBe(true)
  return await response.json() as TagCount[]
}

export async function expectRows(page: Page, expected: PostRow[]): Promise<void> {
  await expect.poll(() => rows(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('data-post-id')))).toEqual(expected.map(post => post.id))
}

export async function expectSelected(page: Page, post: PostRow): Promise<void> {
  await expect(pane(page).getByRole('heading', { name: post.title.trim() || 'Untitled post', exact: true })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe(postPath(post.id))
}

export async function expectStickyMonth(page: Page, posts: PostRow[]): Promise<string> {
  const scroller = sidebar(page).locator('[data-post-list]')
  const visibleId = await rows(page).evaluateAll(nodes => {
    const container = nodes[0].closest('[data-post-list]')!
    const parent = container.getBoundingClientRect()
    const headerHeight = container.querySelector('[data-month]')!.getBoundingClientRect().height
    return nodes.find(node => {
      const bounds = node.getBoundingClientRect()
      return bounds.top >= parent.top + headerHeight && bounds.bottom <= parent.bottom + 1
    })?.getAttribute('data-post-id')
  })
  expect(visibleId).toBeTruthy()
  const post = posts.find(post => post.id === visibleId)!
  const created = new Date(post.created_at)
  const month = created.toISOString().slice(0, 7)
  const label = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(created)
  const pinned = await scroller.locator('[data-month]').evaluateAll(headers => headers.filter(header => {
    const parent = header.closest('[data-post-list]')!.getBoundingClientRect()
    return Math.abs(header.getBoundingClientRect().top - parent.top) <= 1
  }).map(header => ({ month: header.getAttribute('data-month'), label: header.querySelector('span')?.textContent })))
  expect(pinned).toEqual([{ month, label }])
  return month
}

export function postList(posts: PostRow[]): PostList {
  const months = new Map<string, number>()
  for (const post of posts) {
    const month = new Date(post.created_at).toISOString().slice(0, 7)
    months.set(month, (months.get(month) ?? 0) + 1)
  }
  return { rows: posts, total: posts.length, months: [...months].map(([month, count]) => ({ month, count })) }
}

export function largeRows(count = 5000): PostRow[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
    title: `Timeline post ${index + 1}`,
    created_at: new Date(Date.UTC(2026, 10, 1) - index * 86_400_000).toISOString(),
    access: index % 5 === 0 ? 'locked' : 'open',
    counts: { videos: index % 4, images: index % 3, audio: 0, files: 1 },
    cover_path: null,
    favorite: index % 3 === 0,
    match: null,
    missing_media: index % 7 === 0 ? 1 : 0,
    seen: index % 2 === 0,
    tier: index % 5 === 0 ? 'Archive subscriber' : null,
    updated: false,
  }))
}

export function detail(post: PostRow): PostDetail {
  return {
    ...post,
    body_html: '',
    boosty_url: `https://boosty.to/${AUTHOR}/posts/${post.id}`,
    has_folder: true,
    media: [],
    post_price_rub: null,
    tags: ['archive'],
    tier_price_rub: null,
  }
}

/** Keep the actual CLI and assets; replace only the large frontend data envelope. */
export async function installTimeline(page: Page, posts: PostRow[]): Promise<Author> {
  const author = (await actualAuthors(page)).find(author => author.name === AUTHOR)!
  const summary: Author = {
    ...author,
    posts: posts.length,
    locked: posts.filter(post => post.access === 'locked').length,
    unseen: posts.filter(post => !post.seen).length,
    favorites: posts.filter(post => post.favorite).length,
  }
  await page.route(`**${API_PATH}`, route => route.fulfill({ json: summary }))
  await page.route(`**${API_PATH}/tags`, route => route.fulfill({ json: [{ tag: 'archive', count: posts.length }] satisfies TagCount[] }))
  await page.route(`**${API_PATH}/posts`, route => route.fulfill({ json: postList(posts) }))
  await page.route(`**${API_PATH}/posts?*`, route => route.fulfill({ json: postList(posts) }))
  await page.route(`**${API_PATH}/posts/*`, route => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!)
    const post = posts.find(post => post.id === id)
    if (!post) return route.fulfill({ status: 404, json: { error: { code: 'post_not_found', message: 'Post not found.' } } })
    return route.fulfill({ json: detail(post) })
  })
  return summary
}
