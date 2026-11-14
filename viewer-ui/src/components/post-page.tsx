import { Lock } from 'lucide-react'
import type { ReactNode } from 'react'

import { LockedCard } from '@/components/locked-card'
import { PostHeader } from '@/components/post-header'
import { PostPager } from '@/components/post-pager'
import type { PostDetail, PostList } from '@/lib/api.gen'
import type { Filters } from '@/lib/filters'
import { postNeighbours } from '@/lib/post-neighbours'

export type PostPageProps = {
  author: string
  post: PostDetail
  filters: Filters
  posts: PostList | undefined
  listPending: boolean
  favoritePending: boolean
  favoriteError: string | null
  onFavorite: () => void
  onTag: (tag: string) => void
  onPost: (id: string) => void
  postHref: (id: string) => string
  children: ReactNode
}

export function PostPage({ author, post, filters, posts, listPending, favoritePending, favoriteError, onFavorite, onTag, onPost, postHref, children }: PostPageProps) {
  const neighbours = postNeighbours(posts?.rows ?? [], post, filters.order)
  const locked = post.access === 'locked'
  const hasSavedContent = post.body_html.trim().length > 0 || post.has_folder
  return (
    <article className="mx-auto w-full max-w-[760px] px-5 pt-6 pb-12 @2xl/main:px-10 @2xl/main:pt-9 @2xl/main:pb-16">
      <PostHeader post={post} selectedTag={filters.tag} favoritePending={favoritePending} favoriteError={favoriteError} onFavorite={onFavorite} onTag={onTag} />
      <hr className="my-6 border-border @2xl/main:my-7" />
      {locked && !hasSavedContent ? <LockedCard author={author} post={post} /> : (
        <>
          {locked && <SavedAccessNotice />}
          {children}
        </>
      )}
      <PostPager {...neighbours} pending={listPending} onPost={onPost} postHref={postHref} />
    </article>
  )
}

function SavedAccessNotice() {
  return (
    <p className="mb-5 flex items-start gap-2 rounded-lg border bg-card px-4 py-3 text-sm leading-relaxed text-muted-foreground">
      <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      This post is now locked on Boosty. Previously saved content remains available below.
    </p>
  )
}
