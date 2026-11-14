import { cn } from 'cn'
import { Check, CheckCheck, type LucideIcon } from 'lucide-react'

type SeenButtonProps = { seen: boolean; pending: boolean; onToggle: () => void }
type SeenLook = { label: string; action: string; icon: LucideIcon; className: string }

function seenLook(seen: boolean): SeenLook {
  if (seen) {
    return {
      label: 'Seen',
      action: 'Mark as unseen',
      icon: CheckCheck,
      className: 'bg-secondary text-muted-foreground hover:bg-muted',
    }
  }
  return {
    label: 'Mark as seen',
    action: 'Mark as seen',
    icon: Check,
    className: 'bg-primary text-primary-foreground hover:bg-primary/90',
  }
}

export function SeenButton({ seen, pending, onToggle }: SeenButtonProps) {
  const look = seenLook(seen)
  const Icon = look.icon
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={pending}
      aria-label={look.action}
      aria-pressed={seen}
      aria-keyshortcuts="s"
      title={`${look.action} (S)`}
      className={cn(
        'inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[12.5px] font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-wait disabled:opacity-50',
        look.className,
      )}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {look.label}
    </button>
  )
}
