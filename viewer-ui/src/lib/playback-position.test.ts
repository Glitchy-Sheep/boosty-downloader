import { describe, expect, it } from 'vitest'
import { formatPlaybackTime, pendingPlaybackMark, playbackPosition, resumeAt } from '@/lib/playback-position'
import { playbackItem } from '@/test/playback-fixture'

describe('resumeAt', () => {
  it.each([
    { position: 0.9, duration: 100, expected: 0 },
    { position: 1, duration: 100, expected: 1 },
    { position: 94.9, duration: 100, expected: 94.9 },
    { position: 95, duration: 100, expected: 0 },
    { position: 989, duration: 1000, expected: 989 },
    { position: 990, duration: 1000, expected: 0 },
    { position: 9999, duration: 100, expected: 0 },
    { position: NaN, duration: 100, expected: 0 },
    { position: 12, duration: Infinity, expected: 0 },
    { position: 12, duration: 0, expected: 0 },
  ])('resumes $position of $duration at $expected', ({ position, duration, expected }) => {
    expect(resumeAt(playbackItem({ position_s: position }), duration)).toBe(expected)
  })
  it('never resumes a finished piece', () => {
    expect(resumeAt(playbackItem({ finished: true, position_s: 50 }), 100)).toBe(0)
  })
})

describe('playbackPosition', () => {
  it('clamps positions to the known duration', () => {
    expect(playbackPosition(-2, 100)).toEqual({ seconds: 0, duration: 100 })
    expect(playbackPosition(123, 100)).toEqual({ seconds: 100, duration: 100 })
    expect(playbackPosition(1.25, 100)).toEqual({ seconds: 1.25, duration: 100 })
  })
  it.each([NaN, Infinity, -1, 0])('does not save an unknown or empty duration %s', (duration) => {
    expect(playbackPosition(12, duration)).toBeNull()
  })
  it('rejects nonfinite playback times', () => {
    expect(playbackPosition(NaN, 100)).toBeNull()
    expect(playbackPosition(Infinity, 100)).toBeNull()
  })
  it('formats resume notices', () => {
    expect(formatPlaybackTime(65.9)).toBe('1:05')
    expect(formatPlaybackTime(3665)).toBe('1:01:05')
    expect(formatPlaybackTime(NaN)).toBe('0:00')
  })
})

describe('pendingPlaybackMark', () => {
  it('clears finished for Start over and partial playback', () => {
    expect(pendingPlaybackMark({ seconds: 0, duration: 120 })).toEqual({ position_s: 0, finished: false })
    expect(pendingPlaybackMark({ seconds: 40, duration: 120 })).toEqual({ position_s: 40, finished: false })
  })
  it('uses the same finished boundary and zero position as the server', () => {
    expect(pendingPlaybackMark({ seconds: 114, duration: 120 })).toEqual({ position_s: 0, finished: true })
    expect(pendingPlaybackMark({ seconds: 113.9, duration: 120 })).toEqual({ position_s: 113.9, finished: false })
    expect(pendingPlaybackMark({ seconds: 990, duration: 1000 })).toEqual({ position_s: 0, finished: true })
  })
})
