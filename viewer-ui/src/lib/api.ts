import type {
  Author,
  BulkMarksProgressResponse,
  BulkMarksRequest,
  BulkMarksResult,
  ErrorBody,
  FavoriteMarkRequest,
  MarkResult,
  MediaItem,
  MediaPage,
  PositionRequest,
  PostDetail,
  PostList,
  SeenMarkRequest,
  TagCount,
} from '@/lib/api.gen'
import { filtersSearchParams, type Filters } from '@/lib/filters'
import { mediaSearchParams, type MediaSearch } from '@/lib/media-filters'

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
    signal: signal ?? null,
  })
  if (!response.ok) throw await responseError(response, signal)
  return response.json() as Promise<T>
}

async function writeJson<T>(
  url: string,
  body: FavoriteMarkRequest | SeenMarkRequest | BulkMarksRequest | PositionRequest,
  method: 'PUT' | 'POST',
  keepalive = false,
): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    keepalive,
  })
  if (!response.ok) throw await responseError(response)
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

export function getPosts(
  author: string,
  filters: Filters,
  signal?: AbortSignal,
): Promise<PostList> {
  const query = filtersSearchParams(filters).toString()
  const suffix = query ? `?${query}` : ''
  return getJson(`${authorPath(author)}/posts${suffix}`, signal)
}

export function getPost(author: string, postId: string, signal?: AbortSignal): Promise<PostDetail> {
  return getJson(`${authorPath(author)}/posts/${encodeURIComponent(postId)}`, signal)
}

export function getMedia(
  author: string,
  search: MediaSearch,
  signal?: AbortSignal,
): Promise<MediaPage> {
  const query = mediaSearchParams(search).toString()
  return getJson(`${authorPath(author)}/media${query ? `?${query}` : ''}`, signal)
}

export function getTags(author: string, signal?: AbortSignal): Promise<TagCount[]> {
  return getJson(`${authorPath(author)}/tags`, signal)
}

export function setFavorite(
  author: string,
  postId: string,
  favorite: boolean,
): Promise<MarkResult> {
  return writeJson(
    `${authorPath(author)}/posts/${encodeURIComponent(postId)}/marks`,
    { favorite },
    'PUT',
  )
}

export function setSeen(author: string, postId: string, seen: boolean): Promise<MarkResult> {
  return writeJson(
    `${authorPath(author)}/posts/${encodeURIComponent(postId)}/marks`,
    { seen },
    'PUT',
  )
}

export function setSeenMany(author: string, request: BulkMarksRequest): Promise<BulkMarksResult> {
  return writeJson(`${authorPath(author)}/marks`, request, 'POST')
}

export function getMarksProgress(
  author: string,
  signal?: AbortSignal,
): Promise<BulkMarksProgressResponse> {
  return getJson(`${authorPath(author)}/marks/progress`, signal)
}

export function savePlaybackPosition(
  author: string,
  mediaId: string,
  position: PositionRequest,
  keepalive: boolean,
): Promise<MediaItem> {
  if (
    ![position.seconds, position.duration].every((value) => Number.isFinite(value) && value >= 0)
  ) {
    return Promise.reject(
      new Error('Playback position and duration must be finite, nonnegative seconds.'),
    )
  }
  return writeJson(
    `${authorPath(author)}/media/${encodeURIComponent(mediaId)}/position`,
    position,
    'PUT',
    keepalive,
  )
}
