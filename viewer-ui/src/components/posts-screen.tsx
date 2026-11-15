import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useRouter } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { PostBody } from '@/components/post-body'
import { DockedLayout } from '@/components/docked-layout'
import { MobileSidebar } from '@/components/mobile-sidebar'
import { PostPage } from '@/components/post-page'
import { PostPane } from '@/components/post-pane'
import { Sidebar } from '@/components/sidebar'
import { TooltipActive } from '@/lib/tooltip-activity'
import { usePostMarkActions, usePostMarks } from '@/hooks/use-post-marks'
import { usePostShortcuts } from '@/hooks/use-post-shortcuts'
import { useRetainedData } from '@/hooks/use-retained-data'
import type { SavePosition } from '@/hooks/use-post-playback'
import type { AuthorSidebar } from '@/hooks/use-author-sidebar'
import { useSearchController } from '@/hooks/use-search-controller'
import { isAuthorPosts, useTabActive } from '@/lib/author-tab'
import { hasFilters, type Filters } from '@/lib/filters'
import { saveMediaPosition } from '@/lib/playback-mutations'
import { readPostShortcutContext } from '@/lib/post-shortcut-context'
import { authorQuery, postQuery, tagsQuery, usePostList } from '@/lib/queries'
import { stringifyViewerSearch } from '@/lib/url-search'
import type { TimelineSnapshot } from '@/lib/timeline-session'

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
  sidebar,
  children,
}: {
  author: string
  postId: string | undefined
  filters: Filters
  sidebar: AuthorSidebar
  children: ReactNode
}) {
  const active = useTabActive()
  const navigate = useNavigate()
  const router = useRouter()
  const searchResetRevision = useSearchHistoryReset(author)
  const client = useQueryClient()
  const searchInput = useRef<HTMLInputElement>(null)
  const timelineSession = useRef<TimelineSnapshot | null>(null)
  const markActions = usePostMarkActions(author)
  const authorState = useQuery({ ...authorQuery(author), subscribed: active, enabled: active })
  const summary = useRetainedData(authorState.data)
  const posts = usePostList(author, filters, active)
  const postList = useRetainedData(posts.data)
  const tags = useQuery({ ...tagsQuery(author), subscribed: active, enabled: active })
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
    onSearch: () => sidebar.search(searchInput),
    onSidebar: sidebar.toggle,
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
    sidebar.mobile.close()
    void navigate({ to: '/a/$author/p/$postId', params: { author, postId: id }, search: filters })
  }
  const searchController = useSearchController({
    value: filters.q ?? '',
    onSearch: (q) => changeFilters({ ...filters, q: q || undefined }, { replace: true }),
    active,
    navigationRevision: searchResetRevision,
  })
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
  const postSidebar = (
    <TooltipActive value={active && sidebar.isOpen}>
      <Sidebar
        key={author}
        author={summary}
        filters={filters}
        searchController={searchController}
        timelineSession={timelineSession}
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
    </TooltipActive>
  )
  return (
    <>
      <DockedLayout
        controller={sidebar.layout}
        sidebar={postSidebar}
        pane={
          <PostPane author={author} postId={postId}>
            {children}
          </PostPane>
        }
      />
      <MobileSidebar controller={sidebar} searchInput={searchInput}>
        {postSidebar}
      </MobileSidebar>
    </>
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
