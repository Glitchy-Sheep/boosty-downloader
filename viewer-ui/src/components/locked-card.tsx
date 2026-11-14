import { ArrowUpRight, AudioLines, Film, ImageIcon, Lock, Paperclip, type LucideIcon } from 'lucide-react'
import { useState } from 'react'

import type { MediaCounts, PostDetail } from '@/lib/api.gen'
import { formatCount, plural } from '@/lib/format'
import { safeHttpUrl } from '@/lib/post-presentation'

type MediaLabel = { kind: keyof MediaCounts; icon: LucideIcon; one: string; many: string }
const MEDIA: readonly MediaLabel[] = [
  { kind: 'videos', icon: Film, one: 'video', many: 'videos' },
  { kind: 'images', icon: ImageIcon, one: 'photo', many: 'photos' },
  { kind: 'files', icon: Paperclip, one: 'file', many: 'files' },
  { kind: 'audio', icon: AudioLines, one: 'audio track', many: 'audio tracks' },
]

/** A locked post whose body has never been saved in this library. */
export function LockedCard({ author, post }: { author: string; post: PostDetail }) {
  const boostyUrl = safeHttpUrl(post.boosty_url)
  const media = MEDIA.filter(({ kind }) => post.counts[kind] > 0)
  return (
    <section aria-label="Locked post" className="overflow-hidden rounded-[10px] border bg-card">
      <LockedCover key={`${author}/${post.id}`} author={author} post={post} />
      <div className="px-6 pb-6">
        <h2 className="text-[18px] font-semibold tracking-tight">This post is locked</h2>
        <p className="mt-1.5 text-[14px] leading-relaxed text-muted-foreground">The account cannot access this post. Its body has not been saved in this library.</p>
        <AccessDetails post={post} />
        {media.length > 0 && (
          <ul aria-label="Post media" className="mt-4 flex flex-wrap gap-2">
            {media.map(({ kind, icon: Icon, one, many }) => (
              <li key={kind} className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2.5 py-1 text-[12.5px] text-muted-foreground">
                <Icon aria-hidden="true" className="size-3.5" />{plural(post.counts[kind], one, many)}
              </li>
            ))}
          </ul>
        )}
        {boostyUrl && (
          <a href={boostyUrl} target="_blank" rel="noreferrer" className="mt-5 inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50">
            Open on Boosty <ArrowUpRight aria-hidden="true" className="size-4" />
          </a>
        )}
      </div>
    </section>
  )
}

function LockedCover({ author, post }: { author: string; post: PostDetail }) {
  const [failed, setFailed] = useState(false)
  return (
    <div aria-hidden="true" className="relative grid h-56 place-items-center overflow-hidden bg-linear-to-b from-primary-soft to-transparent">
      {post.cover_path && !failed && (
        <>
          <img src={`/thumbs/${encodeURIComponent(author)}/${encodeURIComponent(post.id)}`} alt="" onError={() => setFailed(true)} className="absolute inset-0 size-full object-cover opacity-70" />
          <div className="absolute inset-0 bg-linear-to-t from-card via-card/40 to-transparent" />
        </>
      )}
      <span className="relative grid size-14 place-items-center rounded-full border bg-background/80 shadow-lg backdrop-blur-md"><Lock className="size-6" /></span>
    </div>
  )
}

function AccessDetails({ post }: { post: PostDetail }) {
  return (
    <div className="mt-3 space-y-1 text-[14px] text-muted-foreground">
      {post.tier && <p>Tier: <span className="font-medium text-foreground">{post.tier}</span></p>}
      {post.tier_price_rub !== null && <p>Subscription price: {formatCount(post.tier_price_rub)} ₽ / month</p>}
      {post.post_price_rub !== null && <p>Post price: {formatCount(post.post_price_rub)} ₽</p>}
    </div>
  )
}
