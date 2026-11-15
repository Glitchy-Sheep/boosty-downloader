import { describe, expect, it } from 'vitest'
import { findPlaybackMedia, playerSource } from '@/lib/playback-media'
import { playbackItem } from '@/test/playback-fixture'

const origin = 'http://localhost:8765'

describe('findPlaybackMedia', () => {
  it('matches encoded Unicode, punctuation and literal percent sequences exactly once', () => {
    const item = playbackItem({ path: "folder/Ёж !'()* #?%2F.mp4" })
    const source = '/media/author/folder/%D0%81%D0%B6%20%21%27%28%29%2A%20%23%3F%252F.mp4'
    expect(findPlaybackMedia(source, 'author', 'post', [item], origin)).toBe(item)
    expect(
      findPlaybackMedia(
        source.replace('%21%27%28%29%2A', "!'()*"),
        'author',
        'post',
        [item],
        origin,
      ),
    ).toBe(item)
  })
  it.each([
    'https://evil.test/media/author/post/video.mp4',
    '//evil.test/media/author/post/video.mp4',
    'http://user:password@localhost:8765/media/author/post/video.mp4',
    '/media/other/post/video.mp4',
    '/media/author/post%2Fvideo.mp4',
    '/media/author/post/%ZZvideo.mp4',
    '/media/author/post/%252E%252E/video.mp4',
  ])('rejects a foreign or ambiguous source %s', (source) => {
    expect(findPlaybackMedia(source, 'author', 'post', [playbackItem()], origin)).toBeUndefined()
  })
  it('does not bind another post or a non-player file', () => {
    const source = '/media/author/post/video.mp4'
    expect(findPlaybackMedia(source, 'author', 'other', [playbackItem()], origin)).toBeUndefined()
    expect(
      findPlaybackMedia(source, 'author', 'post', [playbackItem({ kind: 'files' })], origin),
    ).toBeUndefined()
  })
  it('accepts an author encoded as a single path segment', () => {
    expect(
      findPlaybackMedia(
        '/media/%D0%81%D0%B6/post/video.mp4',
        'Ёж',
        'post',
        [playbackItem()],
        origin,
      )?.id,
    ).toBe('opaque-media')
  })
})

describe('playerSource', () => {
  it('finds nested source before native metadata loads', () => {
    const video = document.createElement('video')
    video.innerHTML = '<source src="/media/author/post/video.mp4">'
    expect(playerSource(video)).toBe('/media/author/post/video.mp4')
  })
})
