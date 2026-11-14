import type { Author, ErrorBody, PostDetail, PostList, TagCount } from '@/lib/api.gen'
import { filtersSearchParams, type Filters } from '@/lib/filters'

export class ApiError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function errorBody(value: unknown): ErrorBody | null {
  if (typeof value !== 'object' || value === null || !('error' in value)) return null
  const detail = value.error
  if (typeof detail !== 'object' || detail === null) return null
  if (!('message' in detail) || typeof detail.message !== 'string') return null
  if (!('code' in detail) || typeof detail.code !== 'string') return null
  return { message: detail.message, code: detail.code }
}

async function responseError(response: Response, signal?: AbortSignal): Promise<ApiError> {
  const payload: unknown = await response.json().catch((error: unknown) => {
    signal?.throwIfAborted()
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    return null
  })
  signal?.throwIfAborted()
  const detail = errorBody(payload)
  return new ApiError(
    response.status,
    detail?.message ?? `The library request failed (${response.status}).`,
    detail?.code ?? null,
  )
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) throw await responseError(response, signal)
  return response.json() as Promise<T>
}

function authorPath(author: string): string {
  return `/api/authors/${encodeURIComponent(author)}`
}

export function getAuthors(signal?: AbortSignal): Promise<Author[]> {
  return getJson('/api/authors', signal)
}

export function getAuthor(author: string, signal?: AbortSignal): Promise<Author> {
  return getJson(authorPath(author), signal)
}

export function getPosts(author: string, filters: Filters, signal?: AbortSignal): Promise<PostList> {
  const query = filtersSearchParams(filters).toString()
  const suffix = query ? `?${query}` : ''
  return getJson(`${authorPath(author)}/posts${suffix}`, signal)
}

export function getPost(author: string, postId: string, signal?: AbortSignal): Promise<PostDetail> {
  return getJson(`${authorPath(author)}/posts/${encodeURIComponent(postId)}`, signal)
}

export function getTags(author: string, signal?: AbortSignal): Promise<TagCount[]> {
  return getJson(`${authorPath(author)}/tags`, signal)
}
