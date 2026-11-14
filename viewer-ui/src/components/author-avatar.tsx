import { cn } from 'cn'

import { AuthorArtwork } from '@/components/author-artwork'
import type { Author } from '@/lib/api.gen'

function initials(author: Author): string {
  const name = author.title || author.name
  return name.trim().split(/\s+/u).slice(0, 2)
    .map((word) => Array.from(word)[0] ?? '')
    .join('').toUpperCase()
}

export function AuthorAvatar({ author, className }: { author: Author; className?: string }) {
  return (
    <span aria-hidden="true" className={cn('relative flex size-8 shrink-0 rounded-full bg-muted select-none', className)}>
      <AuthorArtwork
        src={author.avatar_url}
        className="absolute inset-0 size-full rounded-full object-cover"
        fallback={
          <span className="flex size-full items-center justify-center rounded-full text-sm font-semibold text-muted-foreground">
            {initials(author)}
          </span>
        }
      />
    </span>
  )
}
