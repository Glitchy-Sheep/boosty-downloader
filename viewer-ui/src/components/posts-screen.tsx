import { useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { getRouteApi, Outlet, useNavigate, useParams, useRouter } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState } from 'react'

import { PostBody } from '@/components/post-body'
import { PostPage } from '@/components/post-page'
import { Sidebar } from '@/components/sidebar'
import { usePostMarkActions, usePostMarks } from '@/hooks/use-post-marks'
import { usePostShortcuts } from '@/hooks/use-post-shortcuts'
import type { SavePosition } from '@/hooks/use-post-playback'
import { savePlaybackPosition } from '@/lib/api'
import { hasFilters, type Filters } from '@/lib/filters'
import { acceptPosition } from '@/lib/playback-cache'
import { readPostShortcutContext } from '@/lib/post-shortcut-context'
import { authorQuery, postQuery, tagsQuery, usePostList } from '@/lib/queries'
import { stringifyViewerSearch } from '@/lib/url-search'

const postsRoute = getRouteApi('/a/$author/_posts')
const postRoute = getRouteApi('/a/$author/_posts/p/$postId')

function useSearchHistoryReset(): number {
  const router = useRouter()
  const [revision, setRevision] = useState(0)
  useEffect(
    () =>
      router.history.subscribe(({ action }) => {
        switch (action.type) {
          case 'BACK':
          case 'FORWARD':
          case 'GO':
            setRevision((value) => value + 1)
        }
      }),
    [router],
  )
  return revision
}

export function PostsScreen() {
  const { author } = postsRoute.useParams()
  const { postId } = useParams({ strict: false })
  const filters = postsRoute.useSearch()
  const navigate = useNavigate()
  const router = useRouter()
  const searchResetRevision = useSearchHistoryReset()
  const client = useQueryClient()
  const searchInput = useRef<HTMLInputElement>(null)
  const markActions = usePostMarkActions(author)
  const { data: summary } = useSuspenseQuery(authorQuery(author))
  const posts = usePostList(author, filters)
  const tags = useQuery(tagsQuery(author))
  const pane = useRef<HTMLElement>(null)
  useEffect(() => {
    if (pane.current) pane.current.scrollTop = 0
  }, [author, postId])
  usePostShortcuts({
    readContext: () => readPostShortcutContext(client, router.history.location, author),
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

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      <div className="h-[52%] min-h-0 shrink-0 border-b md:h-full md:w-[360px] md:border-r md:border-b-0">
        <Sidebar
          key={author}
          author={summary}
          filters={filters}
          searchResetRevision={searchResetRevision}
          searchInputRef={searchInput}
          posts={posts.data}
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
        <Outlet />
      </section>
    </div>
  )
}

export function EmptyPostList() {
  const filters = postsRoute.useSearch()
  const message = hasFilters(filters)
    ? 'No posts match these filters.'
    : 'No posts saved for this author.'
  return (
    <p role="status" className="p-8 text-muted-foreground">
      {message}
    </p>
  )
}

export function SelectedPost() {
  const { author, postId } = postRoute.useParams()
  return <PostReader key={JSON.stringify([author, postId])} author={author} postId={postId} />
}

function PostReader({ author, postId }: { author: string; postId: string }) {
  const filters = postsRoute.useSearch()
  const client = useQueryClient()
  const navigate = useNavigate()
  const router = useRouter()
  const { data: post } = useSuspenseQuery(postQuery(author, postId))
  const posts = usePostList(author, filters)
  const marks = usePostMarks(author, postId)
  const savePosition = useCallback<SavePosition>(
    async (media, position, options) => {
      const saved = await savePlaybackPosition(author, media.id, position, options.keepalive)
      acceptPosition(client, author, postId, saved)
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
