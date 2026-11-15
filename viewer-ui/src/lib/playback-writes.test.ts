import { describe, expect, it, vi } from 'vitest'
import { createPlaybackWriter } from '@/lib/playback-writes'
import { deferred, playbackItem } from '@/test/playback-fixture'

const identity = {
  origin: 'http://localhost',
  author: 'author',
  postId: 'post',
  mediaId: 'opaque-media',
}

describe('playback writes', () => {
  it('orders delayed requests across old and new player callbacks', async () => {
    const { write } = createPlaybackWriter()
    const pending = deferred()
    const oldSave = vi.fn().mockReturnValue(pending.promise)
    const newSave = vi.fn().mockResolvedValue(undefined)
    const item = playbackItem()
    const first = write(identity, item, { seconds: 15, duration: 100 }, oldSave)
    const last = write(identity, item, { seconds: 0, duration: 100 }, newSave)
    await Promise.resolve()
    expect(oldSave).toHaveBeenCalledExactlyOnceWith(
      item,
      { seconds: 15, duration: 100 },
      { keepalive: true },
    )
    expect(newSave).not.toHaveBeenCalled()
    pending.resolve()
    await Promise.all([first, last])
    expect(newSave).toHaveBeenCalledExactlyOnceWith(
      item,
      { seconds: 0, duration: 100 },
      { keepalive: true },
    )
  })
  it('continues after failure and isolates different identities', async () => {
    const { write } = createPlaybackWriter()
    const pending = deferred()
    const stalled = vi.fn().mockReturnValue(pending.promise)
    const next = vi.fn().mockResolvedValue(undefined)
    const other = vi.fn().mockResolvedValue(undefined)
    const item = playbackItem()
    const first = write(identity, item, { seconds: 10, duration: 100 }, stalled)
    const failure = expect(first).rejects.toThrow('offline')
    const second = write(identity, item, { seconds: 20, duration: 100 }, next)
    await write({ ...identity, author: 'other' }, item, { seconds: 5, duration: 100 }, other)
    expect(other).toHaveBeenCalledOnce()
    expect(next).not.toHaveBeenCalled()
    pending.reject(new Error('offline'))
    await failure
    await second
    expect(next).toHaveBeenCalledOnce()
  })

  it('keeps the newest desired position while older writes settle and removes idle snapshots', async () => {
    const writer = createPlaybackWriter()
    const older = deferred()
    const newer = deferred()
    const item = playbackItem()
    const first = writer.write(identity, item, { seconds: 20, duration: 120 }, () => older.promise)
    const desired = { seconds: 40, duration: 120 }
    const last = writer.write(identity, item, desired, () => newer.promise)
    desired.seconds = 99
    expect(writer.pending(identity)?.position).toEqual({ seconds: 40, duration: 120 })
    expect(writer.pending(identity)?.completion).toBe(last)
    older.resolve()
    await first
    expect(writer.pending(identity)?.position.seconds).toBe(40)
    newer.resolve()
    await last
    await Promise.resolve()
    expect(writer.pending(identity)).toBeUndefined()
  })

  it('drops a failed final snapshot rather than retaining unconfirmed state forever', async () => {
    const writer = createPlaybackWriter()
    const stalled = deferred()
    const request = writer.write(
      identity,
      playbackItem(),
      { seconds: 0, duration: 120 },
      () => stalled.promise,
    )
    const failure = expect(request).rejects.toThrow('offline')
    expect(writer.pending(identity)?.position.seconds).toBe(0)
    stalled.reject(new Error('offline'))
    await failure
    await Promise.resolve()
    expect(writer.pending(identity)).toBeUndefined()
  })
})
