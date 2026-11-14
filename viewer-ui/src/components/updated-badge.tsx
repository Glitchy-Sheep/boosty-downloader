import { cn } from 'cn'

export function UpdatedBadge({ className }: { className?: string }) {
  return (
    <span
      title="New content added since this post was marked seen"
      className={cn(
        'inline-flex shrink-0 items-center rounded-sm border border-primary/20 bg-card px-1 text-[10px] leading-4 font-medium text-primary',
        className,
      )}
    >
      Updated
    </span>
  )
}
