import { Link } from '@tanstack/react-router'
import {
  AudioLines,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  SkipBack,
  SkipForward,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ComponentProps } from 'react'
import { cn } from 'cn'

import { usePlayerPlayback } from '@/hooks/use-player-playback'
import { usePlayerPositions } from '@/hooks/use-player-positions'
import { NO_FILTERS } from '@/lib/filters'
import { mediaPath } from '@/lib/media-paths'
import { attachPlaybackExclusivity } from '@/lib/playback-exclusivity'
import { formatPlaybackTime } from '@/lib/playback-position'
import { currentTrack, usePlayerState, usePlayerStore } from '@/lib/player'

const RATES = [1, 1.25, 1.5, 2, 0.75] as const
const SKIP_SECONDS = 15
const FAILED_TRACK_DELAY = 1500
type PlaybackFailure = { request: number; message: string; advance: boolean }
type PlaybackClock = { request: number; time: number; duration: number }

/** The shell keeps this player outside every author pane and route outlet. */
export function PlayerBar() {
  usePlayerPositions()
  const store = usePlayerStore()
  const state = usePlayerState()
  const track = currentTrack(state)
  const audio = useRef<HTMLAudioElement | null>(null)
  const [clock, setClock] = useState<PlaybackClock | null>(null)
  const [rate, setRate] = useState<number>(1)
  const [failure, setFailure] = useState<PlaybackFailure | null>(null)
  const onFailure = useCallback(
    (request: number, error: unknown): void => {
      if (store.getSnapshot()?.request !== request) return
      if (error instanceof DOMException && error.name === 'AbortError') return
      const denied = error instanceof DOMException && error.name === 'NotAllowedError'
      setFailure({
        request,
        message: denied ? 'Press Play to start this track.' : 'Could not play this track.',
        advance: !denied,
      })
      store.setPlaying(false)
    },
    [store, setFailure],
  )
  const attach = useCallback(
    (element: HTMLAudioElement | null) => {
      audio.current = element
      store.attach(element, onFailure)
    },
    [store, onFailure],
  )
  usePlayerPlayback({ audio, state, store, rate, onFailure })
  useEffect(() => attachPlaybackExclusivity(document), [])
  const request = state?.request
  useEffect(() => {
    if (!failure?.advance || failure.request !== request) return
    const timer = window.setTimeout(() => {
      if (store.getSnapshot()?.request === failure.request) store.step(1)
    }, FAILED_TRACK_DELAY)
    return () => window.clearTimeout(timer)
  }, [failure, request, store])

  if (!state || !track) return null
  const post = state.posts[track.post_id]
  const title = track.title?.trim() || post?.title || track.filename || 'Untitled track'
  const playing = state.playing
  const time = clock && clock.request === request ? clock.time : 0
  const duration = clock && clock.request === request ? clock.duration : (track.duration_s ?? 0)
  const shownFailure = failure && failure.request === request ? failure.message : null
  const updateClock = (): void => {
    if (!audio.current) return
    const length = Number.isFinite(audio.current.duration) ? audio.current.duration : 0
    setClock({ request: state.request, time: audio.current.currentTime, duration: length })
  }
  const seek = (seconds: number): void => {
    const element = audio.current
    if (!element) return
    element.currentTime = Math.min(Math.max(seconds, 0), duration)
    setClock({ request: state.request, time: element.currentTime, duration })
  }
  const skip = (seconds: number): void => {
    seek((audio.current?.currentTime ?? time) + seconds)
  }
  const nextRate = (): void => {
    const index = RATES.findIndex((candidate) => candidate === rate)
    const next = RATES[(index + 1) % RATES.length] ?? 1
    setRate(next)
    if (audio.current) audio.current.playbackRate = next
  }

  return (
    <section aria-label="Player" className="player-bar shrink-0 border-t bg-card">
      <div className="player-bar-layout mx-auto max-w-[1400px] gap-2 px-3 py-2 md:px-6">
        <div className="player-bar-track flex min-w-0 items-center gap-3">
          <div className="grid size-10 shrink-0 place-items-center overflow-hidden rounded-md bg-muted text-muted-foreground">
            {post?.cover_path ? (
              <img
                src={mediaPath(state.author, post.cover_path)}
                alt=""
                className="size-full object-cover"
              />
            ) : (
              <AudioLines aria-hidden="true" className="size-4" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13.5px] font-medium" title={title}>
              {title}
            </div>
            <Link
              to="/a/$author/p/$postId"
              params={{ author: state.author, postId: track.post_id }}
              search={NO_FILTERS}
              className="block truncate text-[12px] text-muted-foreground hover:text-foreground"
            >
              {post?.title || 'Open post'}
            </Link>
          </div>
        </div>
        <div className="player-bar-controls flex items-center justify-center gap-0.5">
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={state.index === 0}
            onClick={() => store.step(-1)}
            aria-label="Previous track"
          >
            <SkipBack />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => skip(-SKIP_SECONDS)}
            aria-label="Back 15 seconds"
          >
            <RotateCcw />
          </Button>
          <Button
            size="icon"
            className="rounded-full"
            onClick={() => {
              void store.toggle()
            }}
            aria-label={playing ? 'Pause' : 'Play'}
          >
            {playing ? <Pause fill="currentColor" /> : <Play fill="currentColor" />}
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => skip(SKIP_SECONDS)}
            aria-label="Forward 15 seconds"
          >
            <RotateCw />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={state.index >= state.queue.length - 1}
            onClick={() => store.step(1)}
            aria-label="Next track"
          >
            <SkipForward />
          </Button>
          <button
            type="button"
            onClick={nextRate}
            className="h-7 min-w-11 rounded-md border px-1.5 text-[12px] font-medium text-muted-foreground tabular-nums hover:text-foreground"
            aria-label="Playback speed"
          >
            {rate}×
          </button>
        </div>
        <div className="player-bar-position flex min-w-0 items-center gap-2 text-[12px] text-muted-foreground tabular-nums">
          <span>{formatPlaybackTime(time)}</span>
          <input
            type="range"
            min={0}
            max={duration}
            step={1}
            value={Math.min(time, duration)}
            onChange={(event) => seek(Number(event.target.value))}
            aria-label="Position"
            className="h-1 min-w-0 flex-1 cursor-pointer accent-(--primary)"
          />
          <span>{formatPlaybackTime(duration)}</span>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          className="player-bar-close"
          onClick={() => store.close()}
          aria-label="Close the player"
        >
          <X />
        </Button>
      </div>
      {shownFailure && (
        <p role="status" className="px-3 pb-2 text-[12px] text-destructive">
          {shownFailure}
        </p>
      )}
      <div className="player-bar-notes">
        {/* Downloaded audio has no transcript metadata to link as a caption track. */}
        {/* oxlint-disable-next-line jsx-a11y/media-has-caption */}
        <audio
          data-player=""
          ref={attach}
          onPlay={() => {
            store.setPlaying(true)
            setFailure(null)
          }}
          onPause={() => store.setPlaying(false)}
          onTimeUpdate={updateClock}
          onDurationChange={updateClock}
          onEnded={() => {
            store.setPlaying(false)
            store.step(1)
          }}
          onError={() => onFailure(state.request, new Error('Media could not load'))}
        />
      </div>
    </section>
  )
}

type PlayerButtonProps = ComponentProps<'button'> & { variant?: 'ghost'; size: 'icon' | 'icon-sm' }

function Button({ variant, size, className, ...props }: PlayerButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        'grid shrink-0 place-items-center rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-40 [&_svg]:size-4',
        variant === 'ghost'
          ? 'text-muted-foreground hover:bg-muted hover:text-foreground'
          : 'bg-primary text-primary-foreground',
        size === 'icon' ? 'size-9' : 'size-7',
        className,
      )}
      {...props}
    />
  )
}
