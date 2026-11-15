export type FileActionIdentity = {
  author: string
  kind: 'media' | 'post'
  id: string
  action: 'open' | 'reveal' | 'copy'
}

export type FileActionNotice =
  | { kind: 'error'; message: string; retry?: () => void; source?: 'capabilities' }
  | { kind: 'path'; message: string; path: string }

export type FileActionState = {
  pending: ReadonlySet<string>
  notice: FileActionNotice | null
  noticeHost: HTMLElement | null
}

export function fileActionKey(identity: FileActionIdentity): string {
  return JSON.stringify({
    author: identity.author,
    kind: identity.kind,
    id: identity.id,
    action: identity.action,
  })
}

export function fileActionError(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'The file action failed.'
}

/** Requests and notices belong to one app, independently of its current pane. */
export function createFileActionController() {
  let state: FileActionState = { pending: new Set(), notice: null, noticeHost: null }
  const listeners = new Set<() => void>()
  const publish = (next: FileActionState): void => {
    state = next
    for (const listener of listeners) listener()
  }
  return {
    getSnapshot: () => state,
    subscribe(this: void, listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    showNotice(notice: FileActionNotice): void {
      publish({ ...state, notice })
    },
    dismissNotice(): void {
      publish({ ...state, notice: null })
    },
    clearCapabilitiesError(): void {
      if (state.notice?.kind === 'error' && state.notice.source === 'capabilities') {
        publish({ ...state, notice: null })
      }
    },
    setNoticeHost(host: HTMLElement): void {
      publish({ ...state, noticeHost: host })
    },
    clearNoticeHost(host: HTMLElement): void {
      if (state.noticeHost === host) publish({ ...state, noticeHost: null })
    },
    async run(
      identity: FileActionIdentity,
      operation: () => Promise<void>,
      onAccepted?: () => void,
    ): Promise<void> {
      const key = fileActionKey(identity)
      if (state.pending.has(key)) return
      publish({ ...state, pending: new Set([...state.pending, key]) })
      try {
        onAccepted?.()
        await operation()
      } catch (error) {
        publish({ ...state, notice: { kind: 'error', message: fileActionError(error) } })
      } finally {
        const pending = new Set(state.pending)
        pending.delete(key)
        publish({ ...state, pending })
      }
    },
  }
}

export type FileActionController = ReturnType<typeof createFileActionController>
