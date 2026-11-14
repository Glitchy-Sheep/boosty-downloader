import type { MediaItem } from '@/lib/api.gen'
import { formatPlaybackTime, playbackPosition, resumeAt } from '@/lib/playback-position'
import type { SavePosition } from '@/lib/playback-writes'

const SAVE_INTERVAL_MS = 5_000

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
): () => void {
  let active = true
  let initialized = false
  let hasActivity = false
  let initialPosition = 0
  let resumeSeekPending = false
  let latestSave = 0
  let interval: ReturnType<typeof setInterval> | undefined
  let resumeNote: HTMLDivElement | undefined
  let errorNote: HTMLDivElement | undefined

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
    if (!hasActivity) return
    const position = playbackPosition(element.currentTime, element.duration)
    if (position) observeSave(savePosition(item, position, { keepalive: true }))
  }

  const startOver = (): void => {
    element.currentTime = 0
    hasActivity = true
    initialPosition = 0
    resumeSeekPending = false
    resumeNote?.remove()
    resumeNote = undefined
    save()
  }

  const initialize = (): void => {
    if (initialized || !Number.isFinite(element.duration) || element.duration <= 0) return
    initialized = true
    if (hasActivity && element.currentTime > 0) return
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
    hasActivity = true
    stopTimer()
    interval = setInterval(() => {
      if (!element.paused && !element.ended) save()
    }, SAVE_INTERVAL_MS)
  }
  const onStop = (): void => {
    stopTimer()
    save()
  }
  const onSeeked = (): void => {
    if (!initialized) return
    if (resumeSeekPending) {
      resumeSeekPending = false
      if (element.currentTime === initialPosition) return
    }
    hasActivity = true
    if (element.paused) save()
  }
  const onHidden = (): void => {
    if (document.visibilityState === 'hidden') save()
  }

  element.addEventListener('loadedmetadata', initialize)
  element.addEventListener('durationchange', initialize)
  element.addEventListener('play', onPlay)
  element.addEventListener('pause', onStop)
  element.addEventListener('ended', onStop)
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
    element.removeEventListener('seeked', onSeeked)
    window.removeEventListener('pagehide', save)
    document.removeEventListener('visibilitychange', onHidden)
    stopTimer()
    save()
    active = false
    if (!element.paused) element.pause()
    resumeNote?.remove()
    errorNote?.remove()
  }
}
