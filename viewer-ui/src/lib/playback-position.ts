import type { MediaItem, PositionRequest } from '@/lib/api.gen'

const END_MARGIN_SECONDS = 10
const END_MARGIN_SHARE = 0.05

type PlaybackMark = Pick<MediaItem, 'position_s' | 'finished'>

function isFinished(seconds: number, duration: number): boolean {
  const margin = Math.min(END_MARGIN_SECONDS, END_MARGIN_SHARE * duration)
  return duration > 0 && seconds >= duration - margin
}

/** Mirror the server's mark while its latest write is still pending. */
export function pendingPlaybackMark(position: PositionRequest): PlaybackMark {
  const finished = isFinished(position.seconds, position.duration)
  return { position_s: finished ? 0 : position.seconds, finished }
}

/** Finished pieces and positions below one second start from the beginning. */
export function resumeAt(
  item: Pick<MediaItem, 'position_s' | 'finished'>,
  duration: number,
): number {
  const saved = item.position_s ?? 0
  if (item.finished || !Number.isFinite(saved) || saved < 1) return 0
  if (!Number.isFinite(duration) || duration <= 0) return 0
  return isFinished(saved, duration) ? 0 : saved
}

export function playbackPosition(seconds: number, duration: number): PositionRequest | null {
  if (!Number.isFinite(seconds) || !Number.isFinite(duration) || duration <= 0) return null
  return { seconds: Math.min(duration, Math.max(0, seconds)), duration }
}

export function formatPlaybackTime(seconds: number): string {
  const whole = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const remainder = String(whole % 60).padStart(2, '0')
  if (hours) return `${hours}:${String(minutes).padStart(2, '0')}:${remainder}`
  return `${minutes}:${remainder}`
}
