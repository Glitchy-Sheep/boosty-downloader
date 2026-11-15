export type FileActionId = 'open' | 'reveal' | 'copy' | 'download' | 'view'

/** Presentation consumes actions without deciding filesystem capabilities. */
export type FileAction =
  | {
      kind: 'command'
      id: 'open' | 'reveal' | 'copy'
      label: string
      hint: string | null
      pending: boolean
      run: () => Promise<void>
    }
  | {
      kind: 'link'
      id: 'download' | 'view'
      label: string
      href: string
      download?: string
      target?: '_blank'
    }
