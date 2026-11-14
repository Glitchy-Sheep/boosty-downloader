import { describe, expect, test } from 'vitest'

import type { Author, MediaStorage } from '@/lib/api.gen'
import { libraryStorage, storageNoun, storageParts } from '@/lib/storage'

const EMPTY_STORAGE: MediaStorage = Object.freeze({ videos: 0, images: 0, files: 0, audio: 0 })

function author(name: string, storage: MediaStorage): Author {
  return {
    name,
    storage,
    title: name,
    description: '',
    avatar_url: null,
    cover_url: null,
    posts: 3,
    unseen: 2,
    locked: 1,
    favorites: 0,
  }
}

describe('storageParts', () => {
  test('orders nonempty kinds by recorded bytes and preserves their shares', () => {
    const storage = Object.freeze({ videos: 500, images: 125, files: 0, audio: 375 })
    const result = storageParts(storage)
    expect(result).toEqual({
      total: 1_000,
      parts: [
        { kind: 'videos', bytes: 500, share: 0.5 },
        { kind: 'audio', bytes: 375, share: 0.375 },
        { kind: 'images', bytes: 125, share: 0.125 },
      ],
    })
    expect(result.parts.reduce((total, part) => total + part.share, 0)).toBe(1)
  })

  test('keeps a deterministic media-kind order for equal sizes', () => {
    expect(storageParts({ audio: 10, files: 10, images: 10, videos: 10 }).parts)
      .toEqual([
        { kind: 'videos', bytes: 10, share: 0.25 },
        { kind: 'images', bytes: 10, share: 0.25 },
        { kind: 'files', bytes: 10, share: 0.25 },
        { kind: 'audio', bytes: 10, share: 0.25 },
      ])
  })

  test('has no bar parts when nothing is downloaded', () => {
    expect(storageParts(EMPTY_STORAGE)).toEqual({ total: 0, parts: [] })
  })

  test('retains a tiny nonzero kind for the visual sliver', () => {
    const result = storageParts({ ...EMPTY_STORAGE, videos: 999_999_999, audio: 1 })
    expect(result.total).toBe(1_000_000_000)
    expect(result.parts[1]).toEqual({ kind: 'audio', bytes: 1, share: 0.000000001 })
  })

  test('returns independent parts without changing the input totals', () => {
    const storage = { ...EMPTY_STORAGE, images: 45_200_000_000 }
    const result = storageParts(storage)
    result.parts[0].bytes = 0
    expect(storage.images).toBe(45_200_000_000)
    expect(storageParts(storage).parts[0].bytes).toBe(45_200_000_000)
  })
})

describe('storageNoun', () => {
  test('names a single media kind instead of the generic total', () => {
    expect(storageNoun(storageParts({ ...EMPTY_STORAGE, images: 45_200_000_000 }).parts)).toBe('photos')
    expect(storageNoun(storageParts({ ...EMPTY_STORAGE, audio: 1 }).parts)).toBe('audio')
  })

  test('uses media for mixed or empty storage', () => {
    expect(storageNoun([])).toBe('media')
    expect(storageNoun(storageParts({ ...EMPTY_STORAGE, images: 1, videos: 2 }).parts)).toBe('media')
  })
})

describe('libraryStorage', () => {
  test('sums each indexed kind across authors without changing their records', () => {
    const first = Object.freeze({
      videos: 263_000_000_000, files: 24_000_000_000, images: 1_650_000_000, audio: 0,
    })
    const second = Object.freeze({
      videos: 0, files: 0, images: 45_200_000_000, audio: 3_000_000_000,
    })
    const authors = Object.freeze([
      author('first', first), author('second', second), author('locked', EMPTY_STORAGE),
    ])
    const total = libraryStorage(authors)
    expect(total).toEqual({
      videos: 263_000_000_000, files: 24_000_000_000, images: 46_850_000_000, audio: 3_000_000_000,
    })
    total.images = 0
    expect(first.images).toBe(1_650_000_000)
    expect(second.images).toBe(45_200_000_000)
  })

  test('returns an empty library with all four supported kinds', () => {
    expect(libraryStorage([])).toEqual(EMPTY_STORAGE)
  })
})
