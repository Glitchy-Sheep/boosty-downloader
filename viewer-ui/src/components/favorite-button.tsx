import { cn } from 'cn'
import { Heart } from 'lucide-react'

type FavoriteButtonProps = {
  favorite: boolean
  pending: boolean
  onToggle: () => void
  className?: string
  iconClassName?: string
  shortcut?: boolean
}

export function FavoriteButton({
  favorite,
  pending,
  onToggle,
  className,
  iconClassName,
  shortcut = false,
}: FavoriteButtonProps) {
  const label = favorite ? 'Remove from favorites' : 'Add to favorites'
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={pending}
      aria-label={label}
      aria-pressed={favorite}
      aria-keyshortcuts={shortcut ? 'f' : undefined}
      title={shortcut ? `${label} (F)` : label}
      className={cn(
        'grid place-items-center rounded-lg text-muted-foreground outline-none transition-colors hover:text-rose-500 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-wait disabled:opacity-50',
        favorite && 'text-rose-500',
        className,
      )}
    >
      <Heart
        aria-hidden="true"
        className={cn('size-4', iconClassName)}
        fill={favorite ? 'currentColor' : 'none'}
      />
    </button>
  )
}
