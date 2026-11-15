import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useRouter } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { PostBody } from '@/components/post-body'
import { PostPage } from '@/components/post-page'
import { Sidebar } from '@/components/sidebar'
import { usePostMarkActions, usePostMarks } from '@/hooks/use-post-marks'
import { usePostShortcuts } from '@/hooks/use-post-shortcuts'
import { useRetainedData } from '@/hooks/use-retained-data'
import type { SavePosition } from '@/hooks/use-post-playback'
import { isAuthorPosts, useTabActive } from '@/lib/author-tab'
import { hasFilters, type Filters } from '@/lib/filters'
import { saveMediaPosition } from '@/lib/playback-mutations'
import { readPostShortcutContext } from '@/lib/post-shortcut-context'
import { authorQuery, postQuery, tagsQuery, usePostList } from '@/lib/queries'
import { stringifyViewerSearch } from '@/lib/url-search'

function useSearchHistoryReset(author: string): number {
  const router = useRouter()
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let previousPath = router.history.location.pathname
    return router.history.subscribe(({ action, location }) => {
      const withinPosts =
        isAuthorPosts(previousPath, author) && isAuthorPosts(location.pathname, author)
      previousPath = location.pathname
      if (!withinPosts) return
      switch (action.type) {
        case 'BACK':
        case 'FORWARD':
        case 'GO':
          setRevision((value) => value + 1)
      }
    })
  }, [router, author])
  return revision
}

export function PostsScreen({
  author,
  postId,
  filters,
  children,
}: {
  author: string
  postId: string | undefined
  filters: Filters
  children: ReactNode
}) {
  const active = useTabActive()
  const navigate = useNavigate()
  const router = useRouter()
  const searchResetRevision = useSearchHistoryReset(author)
  const client = useQueryClient()
  const searchInput = useRef<HTMLInputElement>(null)
  const markActions = usePostMarkActions(author)
  const authorState = useQuery({ ...authorQuery(author), subscribed: active, enabled: active })
  const summary = useRetainedData(authorState.data)
  const posts = usePostList(author, filters, active)
  const postList = useRetainedData(posts.data)
  const tags = useQuery({ ...tagsQuery(author), subscribed: active, enabled: active })
  const pane = useRef<HTMLElement>(null)
  useEffect(() => {
    if (pane.current) pane.current.scrollTop = 0
  }, [author, postId])
  usePostShortcuts({
    readContext: () =>
      active ? readPostShortcutContext(client, router.history.location, author) : null,
    onPost: (target) => {
      void router.navigate({
        to: '/a/$author/p/$postId',
        params: { author: target.author, postId: target.postId },
        search: target.filters,
      })
    },
    onSearch: () => {
      searchInput.current?.focus()
      searchInput.current?.select()
    },
    onSeen: markActions.toggleSeen,
    onFavorite: markActions.toggleFavorite,
  })

  const changeFilters = (next: Filters, options?: { replace?: boolean }): void => {
    if (!active) return
    if (postId) {
      void navigate({
        to: '/a/$author/p/$postId',
        params: { author, postId },
        search: next,
        replace: options?.replace ?? false,
      })
      return
    }
    void navigate({
      to: '/a/$author',
      params: { author },
      search: next,
      replace: options?.replace ?? false,
    })
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

  if (!summary) return <LoadingAuthor />
  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      <div className="h-[52%] min-h-0 shrink-0 border-b md:h-full md:w-[360px] md:border-r md:border-b-0">
        <Sidebar
          key={author}
          author={summary}
          filters={filters}
          searchResetRevision={searchResetRevision}
          searchInputRef={searchInput}
          posts={postList}
          tags={tags.data ?? []}
          currentId={postId}
          loading={posts.isPending}
          updating={posts.isPlaceholderData}
          error={posts.error}
          onRetry={retryPosts}
          tagsError={tags.error}
          onRetryTags={() => {
            void tags.refetch()
          }}
          onFilters={changeFilters}
          onPost={openPost}
          postHref={postHref}
        />
      </div>
      <section
        ref={pane}
        aria-label="Selected post"
        className="@container/main min-h-0 min-w-0 flex-1 overflow-y-auto"
      >
        {children}
      </section>
    </div>
  )
}

export function EmptyPostList({ filters }: { filters: Filters }) {
  const message = hasFilters(filters)
    ? 'No posts match these filters.'
    : 'No posts saved for this author.'
  return (
    <p role="status" className="p-8 text-muted-foreground">
      {message}
    </p>
  )
}

export function PostReader({
  author,
  postId,
  filters,
}: {
  author: string
  postId: string
  filters: Filters
}) {
  const active = useTabActive()
  const client = useQueryClient()
  const navigate = useNavigate()
  const router = useRouter()
  const postState = useQuery({ ...postQuery(author, postId), subscribed: active, enabled: active })
  const post = useRetainedData(postState.data)
  const posts = usePostList(author, filters, active)
  const marks = usePostMarks(author, postId)
  const savePosition = useCallback<SavePosition>(
    async (media, position, options) => {
      await saveMediaPosition(client, author, postId, media, position, options.keepalive)
    },
    [client, author, postId],
  )
  const changeFilters = (patch: Filters): void => {
    void navigate({
      to: '/a/$author/p/$postId',
      params: { author, postId },
      search: { ...filters, ...patch },
    })
  }
  if (!post) return <LoadingPost />
  return (
    <PostPage
      author={author}
      post={post}
      filters={filters}
      posts={posts.data}
      listPending={posts.isPending || posts.isPlaceholderData || posts.isError}
      favoritePending={marks.favorite.pending}
      favoriteError={marks.favorite.error}
      onFavorite={marks.favorite.toggle}
      seenPending={marks.seen.pending}
      seenError={marks.seen.error}
      onSeen={marks.seen.toggle}
      onTag={(tag) => changeFilters({ tag: filters.tag === tag ? undefined : tag })}
      onPost={(id) => {
        void navigate({
          to: '/a/$author/p/$postId',
          params: { author, postId: id },
          search: filters,
        })
      }}
      postHref={(id) =>
        `/a/${encodeURIComponent(author)}/p/${encodeURIComponent(id)}${stringifyViewerSearch(filters)}`
      }
    >
      <PostBody
        author={author}
        postId={postId}
        html={post.body_html}
        media={post.media}
        query={filters.q}
        onClearSearch={() => changeFilters({ q: undefined })}
        onNavigate={(href) => {
          void router.navigate({ href })
        }}
        savePosition={savePosition}
      />
    </PostPage>
  )
}

export function LoadingAuthor() {
  return (
    <p role="status" className="p-8 text-muted-foreground">
      Loading author...
    </p>
  )
}

export function LoadingPost() {
  return (
    <p role="status" className="p-8 text-muted-foreground">
      Loading post...
    </p>
  )
}
