import type { MediaItem, PositionRequest } from '@/lib/api.gen'

export interface PositionSaveOptions {
  keepalive: boolean
}

export type SavePosition = (
  media: MediaItem,
  position: PositionRequest,
  options: PositionSaveOptions,
) => Promise<void>

export interface PlaybackIdentity {
  origin: string
  author: string
  postId: string
  mediaId: string
}

export interface PendingPlaybackSave {
  readonly position: Readonly<PositionRequest>
  readonly completion: Promise<void>
}

export interface PlaybackActivity {
  claim: () => void
  owns: () => boolean
  release: () => void
}

interface PlaybackWriteState {
  tail: Promise<void>
  pending: PendingPlaybackSave
}

function identityKey(identity: PlaybackIdentity): string {
  return JSON.stringify({
    origin: identity.origin,
    author: identity.author,
    postId: identity.postId,
    mediaId: identity.mediaId,
  })
}

/** Active writes share an order across player remounts; idle queues retain nothing. */
export function createPlaybackWriter() {
  const active = new Map<string, PlaybackWriteState>()
  const owners = new Map<string, symbol>()
  const activity = (identity: PlaybackIdentity): PlaybackActivity => {
    const key = identityKey(identity)
    const owner = Symbol('playback activity')
    return {
      claim: () => {
        owners.set(key, owner)
      },
      owns: () => owners.get(key) === owner,
      release: () => {
        if (owners.get(key) === owner) owners.delete(key)
      },
    }
  }
  const write = (
    identity: PlaybackIdentity,
    media: MediaItem,
    position: PositionRequest,
    save: SavePosition,
  ): Promise<void> => {
    const key = identityKey(identity)
    const previous = active.get(key)?.tail ?? Promise.resolve()
    const desired = { ...position }
    // Keep in-flight requests eligible for delivery after pagehide.
    const request = previous.then(() => save(media, desired, { keepalive: true }))
    const settled = request.catch(() => undefined)
    const state = { tail: settled, pending: { position: desired, completion: request } }
    active.set(key, state)
    void settled.then(() => {
      if (active.get(key) === state) active.delete(key)
    })
    return request
  }
  const pending = (identity: PlaybackIdentity): PendingPlaybackSave | undefined =>
    active.get(identityKey(identity))?.pending
  return { write, pending, activity }
}

export type PlaybackWriter = ReturnType<typeof createPlaybackWriter>
const playbackWriter = createPlaybackWriter()
export const writePlaybackPosition = playbackWriter.write
export const pendingPlaybackPosition = playbackWriter.pending
export const createPlaybackActivity = playbackWriter.activity
