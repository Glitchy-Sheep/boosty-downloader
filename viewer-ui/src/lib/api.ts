import type { Author, ErrorBody } from '@/lib/api.gen'

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

export async function getAuthors(signal?: AbortSignal): Promise<Author[]> {
  const response = await fetch('/api/authors', {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) throw await responseError(response, signal)
  return response.json() as Promise<Author[]>
}
