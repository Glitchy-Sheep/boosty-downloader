import type { MediaItem } from '@/lib/api.gen'

export function playbackItem(overrides: Partial<MediaItem> = {}): MediaItem {
  return {
    id: 'opaque-media',
    post_id: 'post',
    path: 'post/video.mp4',
    kind: 'videos',
    file_type: 'video',
    filename: 'video.mp4',
    title: 'Video',
    artist: null,
    created_at: '2026-11-01T00:00:00Z',
    duration_s: 120,
    position_s: 12,
    finished: false,
    height: null,
    width: null,
    thumb_path: null,
    size: 100,
    removed: false,
    ...overrides,
  }
}

export function nativePlayer(
  parent: HTMLElement,
  tag: 'video' | 'audio' = 'video',
): HTMLMediaElement {
  const element = document.createElement(tag)
  element.src = '/media/author/post/video.mp4'
  Object.defineProperties(element, {
    duration: { configurable: true, value: 120, writable: true },
    readyState: { configurable: true, value: 1, writable: true },
    paused: { configurable: true, value: true, writable: true },
    ended: { configurable: true, value: false, writable: true },
  })
  parent.append(element)
  return element
}

export function setPlaying(element: HTMLMediaElement): void {
  Object.defineProperty(element, 'paused', { configurable: true, value: false, writable: true })
  element.dispatchEvent(new Event('play'))
}

export function deferred() {
  let resolve!: () => void
  let reject!: (error: Error) => void
  const promise = new Promise<void>((accept, decline) => {
    resolve = accept
    reject = decline
  })
  return { promise, resolve, reject }
}
