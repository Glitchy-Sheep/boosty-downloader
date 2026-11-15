import {
  Copy,
  Download,
  Ellipsis,
  Eye,
  FolderOpen,
  SquareArrowOutUpRight,
  type LucideIcon,
} from 'lucide-react'
import { ContextMenu, DropdownMenu, Toolbar, Tooltip } from 'radix-ui'
import {
  Fragment,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type RefObject,
} from 'react'

import { useTabActive } from '@/lib/author-tab'
import type { FileAction, FileActionId } from '@/lib/file-action-types'

type FileActionsProps = {
  actions: readonly FileAction[]
  mode: 'file' | 'media' | 'menu'
  label: string
  active?: boolean
}
type MenuKind = 'dropdown' | 'context'
const ICONS = {
  open: SquareArrowOutUpRight,
  reveal: FolderOpen,
  copy: Copy,
  download: Download,
  view: Eye,
} satisfies Record<FileActionId, typeof Copy>

/** One pointer gesture must begin and finish on the action it activates. */
function useActionGesture(action: FileAction) {
  const pointer = useRef<{ id: number; released: boolean } | null>(null)
  const blocked = useRef(false)
  return {
    onPointerDown(event: PointerEvent<HTMLElement>) {
      const primary = event.button === 0 && event.isPrimary !== false
      pointer.current = primary ? { id: event.pointerId, released: false } : null
      blocked.current = !primary
    },
    onPointerUp(event: PointerEvent<HTMLElement>) {
      const pressed = pointer.current
      if (event.button === 0 && pressed?.id === event.pointerId) pressed.released = true
      else {
        pointer.current = null
        blocked.current = true
        event.preventDefault()
      }
    },
    onPointerCancel() {
      pointer.current = null
      blocked.current = true
    },
    onPointerLeave() {
      // Touch pointers leave the target before their click is dispatched.
      if (!pointer.current?.released) pointer.current = null
    },
    onKeyDown(event: KeyboardEvent<HTMLElement>) {
      if (event.key !== 'Enter' && event.key !== ' ') return
      if (event.repeat) event.preventDefault()
      else {
        blocked.current = false
        pointer.current = null
      }
    },
    onClick(event: MouseEvent<HTMLElement>) {
      event.stopPropagation()
      const allowed = !blocked.current && (event.detail === 0 || pointer.current?.released)
      pointer.current = null
      if (!allowed || event.detail > 1 || (action.kind === 'command' && action.pending)) {
        event.preventDefault()
        return
      }
      if (action.kind === 'command') void action.run()
    },
  }
}

function useFoldedActions(
  root: RefObject<HTMLDivElement | null>,
  mode: FileActionsProps['mode'],
  active: boolean,
): boolean {
  const [folded, setFolded] = useState(true)
  useLayoutEffect(() => {
    if (!active || mode === 'menu') return
    const hover = window.matchMedia('(hover: hover)')
    const wide = window.matchMedia('(min-width: 640px)')
    const container =
      root.current?.closest('[data-file-action-container]') ?? root.current?.parentElement
    const update = () => {
      const enough =
        mode === 'media' ? wide.matches : (container?.getBoundingClientRect().width ?? 0) >= 512
      setFolded(!hover.matches || !enough)
    }
    const observer = new ResizeObserver(update)
    if (container) observer.observe(container)
    hover.addEventListener('change', update)
    wide.addEventListener('change', update)
    update()
    return () => {
      observer.disconnect()
      hover.removeEventListener('change', update)
      wide.removeEventListener('change', update)
    }
  }, [active, mode, root])
  return mode === 'menu' || folded
}

/** File rows expose all actions; media keeps secondary actions in its menu. */
export function FileActions({ actions, mode, label, active: explicitActive }: FileActionsProps) {
  const tabActive = useTabActive()
  const active = explicitActive ?? tabActive
  const root = useRef<HTMLDivElement>(null)
  const folded = useFoldedActions(root, mode, active && actions.length > 0)
  const latestActive = useRef(active)
  const [menuState, setMenuState] = useState({ open: false, folded })
  if ((!active || menuState.folded !== folded) && menuState.open)
    setMenuState({ open: false, folded })
  useLayoutEffect(() => {
    latestActive.current = active
    return () => {
      latestActive.current = false
    }
  }, [active])
  const direct = folded
    ? []
    : actions.filter((action) => mode === 'file' || action.id === 'open' || action.id === 'reveal')
  const menu = actions.filter((action) => !direct.includes(action))
  if (!active || actions.length === 0) return null
  return (
    <Tooltip.Provider delayDuration={350}>
      <Toolbar.Root
        ref={root}
        aria-label={label}
        className="file-actions"
        data-mode={mode}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        {direct.map((action, index) => (
          <Fragment key={action.id}>
            {index > 0 && direct[index - 1]?.id === 'open' && (
              <Toolbar.Separator className="file-action-divider" />
            )}
            <FileActionControl action={action} inToolbar />
          </Fragment>
        ))}
        {menu.length > 0 && (
          <DropdownMenu.Root
            open={menuState.open}
            onOpenChange={(open) => setMenuState({ open, folded })}
          >
            <DropdownMenu.Trigger asChild>
              <Toolbar.Button
                className="file-action-button"
                aria-label={`More for ${label}`}
                title="More actions"
              >
                <Ellipsis aria-hidden="true" />
              </Toolbar.Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                aria-label={label}
                align="end"
                sideOffset={6}
                className="file-action-menu"
                onKeyDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
                onCloseAutoFocus={(event) => {
                  if (!latestActive.current) event.preventDefault()
                }}
              >
                <FileMenuItems actions={menu} kind="dropdown" />
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        )}
      </Toolbar.Root>
    </Tooltip.Provider>
  )
}

/** A standalone action uses the same gesture and tooltip contract as a file toolbar. */
export function FileActionButton({
  action,
  icon,
  active: explicitActive,
}: {
  action: FileAction
  icon?: LucideIcon
  active?: boolean
}) {
  const tabActive = useTabActive()
  if (!(explicitActive ?? tabActive)) return null
  return (
    <Tooltip.Provider delayDuration={350}>
      <FileActionControl action={action} icon={icon} />
    </Tooltip.Provider>
  )
}

function FileActionControl({
  action,
  icon,
  inToolbar = false,
}: {
  action: FileAction
  icon?: LucideIcon | undefined
  inToolbar?: boolean
}) {
  const gesture = useActionGesture(action)
  const Icon = icon ?? ICONS[action.id]
  const Link = inToolbar ? Toolbar.Link : 'a'
  const Button = inToolbar ? Toolbar.Button : 'button'
  const control =
    action.kind === 'link' ? (
      <Link
        {...gesture}
        href={action.href}
        download={action.download}
        target={action.target}
        rel={action.target ? 'noreferrer' : undefined}
        aria-label={action.label}
        data-action={action.id}
        className="file-action-button"
      >
        <Icon aria-hidden="true" />
      </Link>
    ) : (
      <Button
        {...gesture}
        type="button"
        disabled={action.pending}
        aria-label={action.label}
        aria-description={action.hint ?? undefined}
        data-action={action.id}
        className="file-action-button"
      >
        <Icon aria-hidden="true" />
      </Button>
    )
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{control}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content sideOffset={6} className="file-action-tooltip">
          {action.label}
          {action.kind === 'command' && action.hint && <span> {action.hint}</span>}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

/** Dropdown and context menus share item order, hints and gesture guards. */
export function FileMenuItems({
  actions,
  kind,
}: {
  actions: readonly FileAction[]
  kind: MenuKind
}) {
  const Separator = kind === 'dropdown' ? DropdownMenu.Separator : ContextMenu.Separator
  return actions.map((action, index) => (
    <Fragment key={action.id}>
      {index > 0 && (actions[index - 1]?.id === 'open' || action.id === 'download') && (
        <Separator className="file-action-menu-divider" />
      )}
      <FileMenuItem action={action} kind={kind} />
    </Fragment>
  ))
}

function FileMenuItem({ action, kind }: { action: FileAction; kind: MenuKind }) {
  const Item = kind === 'dropdown' ? DropdownMenu.Item : ContextMenu.Item
  const gesture = useActionGesture(action)
  const Icon = ICONS[action.id]
  const content = (
    <>
      <Icon aria-hidden="true" />
      <span>
        {action.label}
        {action.kind === 'command' && action.hint && <small> {action.hint}</small>}
      </span>
    </>
  )
  if (action.kind === 'link') {
    return (
      <Item asChild className="file-action-menu-item" {...gesture}>
        <a
          href={action.href}
          download={action.download}
          target={action.target}
          rel={action.target ? 'noreferrer' : undefined}
          data-action={action.id}
        >
          {content}
        </a>
      </Item>
    )
  }
  return (
    <Item
      {...gesture}
      disabled={action.pending}
      aria-label={action.label}
      aria-description={action.hint ?? undefined}
      data-action={action.id}
      className="file-action-menu-item"
    >
      {content}
    </Item>
  )
}
