import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { getRouteApi, Outlet, useNavigate, useParams, useRouter } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { Sidebar } from '@/components/sidebar'
import { formatDate } from '@/lib/dates'
import { hasFilters, type Filters } from '@/lib/filters'
import { authorQuery, postQuery, tagsQuery, usePostList } from '@/lib/queries'
import { stringifyViewerSearch } from '@/lib/url-search'

const postsRoute = getRouteApi('/a/$author/_posts')
const postRoute = getRouteApi('/a/$author/_posts/p/$postId')

function useSearchHistoryReset(): number {
  const router = useRouter()
  const [revision, setRevision] = useState(0)
  useEffect(() => router.history.subscribe(({ action }) => {
    switch (action.type) {
      case 'BACK':
      case 'FORWARD':
      case 'GO':
        setRevision(value => value + 1)
    }
  }), [router])
  return revision
}

export function PostsScreen() {
  const { author } = postsRoute.useParams()
  const { postId } = useParams({ strict: false })
  const filters = postsRoute.useSearch()
  const navigate = useNavigate()
  const router = useRouter()
  const searchResetRevision = useSearchHistoryReset()
  const { data: summary } = useSuspenseQuery(authorQuery(author))
  const posts = usePostList(author, filters)
  const tags = useQuery(tagsQuery(author))

  const changeFilters = (next: Filters, options?: { replace?: boolean }): void => {
    if (postId) {
      void navigate({ to: '/a/$author/p/$postId', params: { author, postId }, search: next, replace: options?.replace })
      return
    }
    void navigate({ to: '/a/$author', params: { author }, search: next, replace: options?.replace })
  }
  const openPost = (id: string): void => {
    void navigate({ to: '/a/$author/p/$postId', params: { author, postId: id }, search: filters })
  }
  const postHref = (id: string): string =>
    `/a/${encodeURIComponent(author)}/p/${encodeURIComponent(id)}${stringifyViewerSearch(filters)}`
  const retryPosts = (): void => {
    if (!postId) {
      void router.invalidate()
      return
    }
    void posts.refetch()
  }

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      <div className="h-[52%] min-h-0 shrink-0 border-b md:h-full md:w-[360px] md:border-r md:border-b-0">
        <Sidebar
          key={author}
          author={summary}
          filters={filters}
          searchResetRevision={searchResetRevision}
          posts={posts.data}
          tags={tags.data ?? []}
          currentId={postId}
          loading={posts.isPending}
          updating={posts.isPlaceholderData}
          error={posts.error}
          onRetry={retryPosts}
          tagsError={tags.error}
          onRetryTags={() => { void tags.refetch() }}
          onFilters={changeFilters}
          onPost={openPost}
          postHref={postHref}
        />
      </div>
      <section aria-label="Selected post" className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </section>
    </div>
  )
}

export function EmptyPostList() {
  const filters = postsRoute.useSearch()
  const message = hasFilters(filters) ? 'No posts match these filters.' : 'No posts saved for this author.'
  return <p role="status" className="p-8 text-muted-foreground">{message}</p>
}

export function SelectedPost() {
  const { author, postId } = postRoute.useParams()
  const { data: post } = useSuspenseQuery(postQuery(author, postId))
  const title = post.title.trim() ? post.title : 'Untitled post'
  return (
    <article className="mx-auto max-w-[900px] p-6 sm:p-10">
      <time dateTime={post.created_at} className="text-sm text-muted-foreground">{formatDate(post.created_at)}</time>
      <h1 className="mt-2 text-2xl font-semibold wrap-anywhere">{title}</h1>
      {post.access === 'locked' && <p className="mt-3 text-sm text-muted-foreground">Locked{post.tier && ` · ${post.tier}`}</p>}
      {post.tags.length > 0 && (
        <ul aria-label="Post tags" className="mt-4 flex flex-wrap gap-2 text-sm text-muted-foreground">
          {post.tags.map(tag => <li key={tag} className="rounded-md border px-2 py-1 wrap-anywhere">{tag}</li>)}
        </ul>
      )}
    </article>
  )
}

export function LoadingAuthor() {
  return <p role="status" className="p-8 text-muted-foreground">Loading author...</p>
}

export function LoadingPost() {
  return <p role="status" className="p-8 text-muted-foreground">Loading post...</p>
}
