import type { MediaItem, PositionRequest } from '@/lib/api.gen'
import { formatPlaybackTime, playbackPosition, resumeAt } from '@/lib/playback-position'
import type { PlaybackActivity, SavePosition } from '@/lib/playback-writes'

const SAVE_INTERVAL_MS = 5_000
type PositionAttempt = { position: PositionRequest; failed: boolean }
type InitialSeekState = 'none' | 'pending' | 'completed'

function samePosition(left: PositionRequest, right: PositionRequest): boolean {
  return left.seconds === right.seconds && left.duration === right.duration
}

function generatedNote(className: string): HTMLDivElement {
  const note = document.createElement('div')
  note.className = className
  note.dataset.pageGenerated = 'true'
  return note
}

/** Bind one native player without replacing its element or authored content. */
export function attachPostPlayback(
  element: HTMLMediaElement,
  item: MediaItem,
  savePosition: SavePosition,
  pendingSave?: Promise<void>,
  activity?: PlaybackActivity,
): () => void {
  let active = true
  let initialized = false
  let hasActivity = false
  let initialSeek: InitialSeekState = 'none'
  let initialPosition = 0
  let resumeSeekPending = false
  let latestSave = 0
  let interval: ReturnType<typeof setInterval> | undefined
  let resumeNote: HTMLDivElement | undefined
  let errorNote: HTMLDivElement | undefined
  let latestAttempt: PositionAttempt | undefined

  const stopTimer = (): void => {
    clearInterval(interval)
    interval = undefined
  }

  const observeSave = (request: Promise<void>): void => {
    const revision = ++latestSave
    void request
      .then(() => {
        if (!active || revision !== latestSave) return
        errorNote?.remove()
        errorNote = undefined
      })
      .catch(() => {
        if (!active || revision !== latestSave || errorNote) return
        errorNote = generatedNote('playback-save-error')
        errorNote.setAttribute('role', 'status')
        errorNote.textContent = 'Playback position could not be saved.'
        element.after(errorNote)
      })
  }

  const save = (): void => {
    if (!initialized || !hasActivity) return
    const position = playbackPosition(element.currentTime, element.duration)
    if (!position) return
    const previous = latestAttempt
    if (previous && samePosition(previous.position, position)) {
      const superseded = activity && !activity.owns()
      if (!previous.failed || superseded) return
    }
    if (activity && !activity.owns()) {
      if (!previous || previous.position.seconds === position.seconds) return
      // Further playback is new activity; an unchanged paused retry cannot reclaim it.
      activity.claim()
    }
    const attempt = { position, failed: false }
    latestAttempt = attempt
    const request = savePosition(item, position, { keepalive: true }).catch((error: unknown) => {
      attempt.failed = true
      throw error
    })
    observeSave(request)
  }

  const startOver = (): void => {
    activity?.claim()
    element.currentTime = 0
    hasActivity = true
    latestAttempt = undefined
    initialPosition = 0
    resumeSeekPending = false
    resumeNote?.remove()
    resumeNote = undefined
    save()
  }

  const finishSeek = (): void => {
    hasActivity = true
    activity?.claim()
    latestAttempt = undefined
    if (element.paused) save()
  }

  const initialize = (): void => {
    if (initialized || !Number.isFinite(element.duration) || element.duration <= 0) return
    initialized = true
    if (initialSeek !== 'none') {
      if (initialSeek === 'completed' && element.paused) save()
      return
    }
    initialPosition = resumeAt(item, element.duration)
    if (!initialPosition) return
    resumeSeekPending = true
    element.currentTime = initialPosition
    resumeNote = generatedNote('resume-note')
    resumeNote.append(`Resumed at ${formatPlaybackTime(initialPosition)} `)
    const restart = document.createElement('button')
    restart.type = 'button'
    restart.textContent = 'Start over'
    restart.addEventListener('click', startOver)
    resumeNote.append(restart)
    element.after(resumeNote)
  }

  const onPlay = (): void => {
    activity?.claim()
    hasActivity = true
    latestAttempt = undefined
    stopTimer()
    interval = setInterval(() => {
      if (!element.paused && !element.ended) save()
    }, SAVE_INTERVAL_MS)
  }
  const onStop = (): void => {
    stopTimer()
    save()
  }
  const onSeeking = (): void => {
    if (!initialized) initialSeek = 'pending'
  }
  const onSeeked = (): void => {
    if (!initialized) {
      initialSeek = 'completed'
      finishSeek()
      return
    }
    if (resumeSeekPending) {
      resumeSeekPending = false
      if (element.currentTime === initialPosition) return
    }
    finishSeek()
  }
  const onHidden = (): void => {
    if (document.visibilityState === 'hidden') save()
  }

  element.addEventListener('loadedmetadata', initialize)
  element.addEventListener('durationchange', initialize)
  element.addEventListener('play', onPlay)
  element.addEventListener('pause', onStop)
  element.addEventListener('ended', onStop)
  element.addEventListener('seeking', onSeeking)
  element.addEventListener('seeked', onSeeked)
  window.addEventListener('pagehide', save)
  document.addEventListener('visibilitychange', onHidden)
  if (pendingSave) observeSave(pendingSave)
  if (element.readyState >= HTMLMediaElement.HAVE_METADATA) initialize()

  return () => {
    element.removeEventListener('loadedmetadata', initialize)
    element.removeEventListener('durationchange', initialize)
    element.removeEventListener('play', onPlay)
    element.removeEventListener('pause', onStop)
    element.removeEventListener('ended', onStop)
    element.removeEventListener('seeking', onSeeking)
    element.removeEventListener('seeked', onSeeked)
    window.removeEventListener('pagehide', save)
    document.removeEventListener('visibilitychange', onHidden)
    stopTimer()
    save()
    active = false
    activity?.release()
    if (!element.paused) element.pause()
    resumeNote?.remove()
    errorNote?.remove()
  }
}
