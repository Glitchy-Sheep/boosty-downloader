import { getRouteApi, Link, useLocation, useMatch } from '@tanstack/react-router'
import { cn } from 'cn'
import { Images, Newspaper, PanelLeft } from 'lucide-react'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { MediaScreen } from '@/components/media-screen'
import { EmptyPostList, LoadingPost, PostReader, PostsScreen } from '@/components/posts-screen'
import { LoadError } from '@/components/route-screens'
import { ControlTooltip } from '@/components/ui/control-tooltip'
import { useDockedSidebar } from '@/hooks/use-docked-sidebar'
import { useMediaQuery } from '@/hooks/use-media-query'
import {
  pendingPostPlace,
  retainAuthorPlace,
  type AuthorPlaces,
  type PostsPlace,
  type ShownPlace,
} from '@/lib/author-places'
import { authorTab, TabActive, type AuthorTab } from '@/lib/author-tab'
import { NO_FILTERS } from '@/lib/filters'
import { useHeaderSlots } from '@/lib/header-slots'
import { NO_MEDIA_FILTERS } from '@/lib/media-filters'
import { readPostAddress } from '@/lib/post-address'
import { DOCKED_QUERY } from '@/lib/sidebar-layout'

const authorRoute = getRouteApi('/a/$author')

export function AuthorShell() {
  const { author } = authorRoute.useParams()
  return <AuthorTabs key={author} author={author} />
}

function AuthorTabs({ author }: { author: string }) {
  const location = useLocation()
  const addressTab = authorTab(location.pathname)
  const incoming = useReadyPlace()
  const [firstTab] = useState(addressTab)
  const [kept, setKept] = useState<AuthorPlaces>({
    shown: null,
    posts: undefined,
    media: undefined,
  })
  const address = readPostAddress({ pathname: location.pathname, search: location.searchStr })
  const places = retainAuthorPlace(kept, pendingPostPlace(kept, incoming, address))
  if (places !== kept) setKept(places)
  const { posts, media, shown } = places
  const { start } = useHeaderSlots()
  const toggleRef = useRef<HTMLButtonElement>(null)
  const docked = useMediaQuery(DOCKED_QUERY)
  const postsActive = shown === 'posts' && addressTab === 'posts'
  const sidebar = useDockedSidebar({ active: postsActive, docked, toggleRef })
  const sidebarLabel = sidebar.isOpen ? 'Hide sidebar' : 'Show sidebar'

  return (
    <>
      <HeaderTabs author={author} tab={addressTab} places={places} />
      {start &&
        createPortal(
          <ControlTooltip label={`${sidebarLabel} ([)`} active={postsActive && docked}>
            <button
              ref={toggleRef}
              type="button"
              aria-label={sidebarLabel}
              aria-expanded={sidebar.isOpen}
              aria-controls="author-post-sidebar"
              aria-keyshortcuts="["
              disabled={!postsActive || !docked}
              onClick={sidebar.toggle}
              className={cn(
                'flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50',
                (!postsActive || !docked) && 'invisible',
              )}
            >
              <PanelLeft aria-hidden="true" className="size-4" />
            </button>
          </ControlTooltip>,
          start,
        )}
      <div className="relative h-full overflow-clip">
        {!shown && <LoadingPost />}
        {posts && (
          <AuthorPane
            tab="posts"
            shown={shown === 'posts'}
            active={postsActive}
            slidesIn={firstTab !== 'posts'}
          >
            <PostsScreen
              author={author}
              postId={posts.postId}
              filters={posts.filters}
              sidebar={sidebar}
            >
              <PostContent author={author} place={posts} />
            </PostsScreen>
          </AuthorPane>
        )}
        {media && (
          <AuthorPane
            tab="media"
            shown={shown === 'media'}
            active={shown === 'media' && addressTab === 'media'}
            slidesIn={firstTab !== 'media'}
          >
            {media.error === undefined ? (
              <MediaScreen author={author} filters={media.filters} />
            ) : (
              <LoadError error={media.error} />
            )}
          </AuthorPane>
        )}
      </div>
    </>
  )
}

function PostContent({ author, place }: { author: string; place: PostsPlace }) {
  if (place.shows === 'loading') return <LoadingPost />
  if (place.shows === 'error') return <LoadError error={place.error} />
  if (place.shows === 'empty' || !place.postId) return <EmptyPostList filters={place.filters} />
  return (
    <PostReader key={place.postId} author={author} postId={place.postId} filters={place.filters} />
  )
}

function useReadyPlace(): ShownPlace | null {
  const media = useMatch({ from: '/a/$author/media', shouldThrow: false })
  const posts = useMatch({ from: '/a/$author/_posts', shouldThrow: false })
  const list = useMatch({ from: '/a/$author/_posts/', shouldThrow: false })
  const post = useMatch({ from: '/a/$author/_posts/p/$postId', shouldThrow: false })
  if (media) {
    if (media.isFetching || (media.status !== 'success' && media.status !== 'error')) return null
    return {
      tab: 'media',
      place: { filters: media.search, error: media.status === 'error' ? media.error : undefined },
    }
  }
  const match = post ?? list
  if (
    !match ||
    posts?.isFetching ||
    match.isFetching ||
    (match.status !== 'success' && match.status !== 'error')
  )
    return null
  return {
    tab: 'posts',
    place: {
      filters: posts?.search ?? NO_FILTERS,
      postId: post?.params.postId,
      shows: postPresentation(match.status === 'error', post !== undefined),
      error: match.status === 'error' ? match.error : undefined,
    },
  }
}

function postPresentation(failed: boolean, selected: boolean): PostsPlace['shows'] {
  if (failed) return 'error'
  return selected ? 'post' : 'empty'
}

function AuthorPane({
  tab,
  shown,
  active,
  slidesIn,
  children,
}: {
  tab: AuthorTab
  shown: boolean
  active: boolean
  slidesIn: boolean
  children: ReactNode
}) {
  const pane = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (active) return
    for (const player of pane.current?.querySelectorAll<HTMLMediaElement>('video, audio') ?? [])
      player.pause()
  }, [active])
  return (
    <div
      ref={pane}
      data-tab={tab}
      data-shown={shown ? '' : undefined}
      data-slides-in={slidesIn ? '' : undefined}
      inert={!active}
      className="author-pane"
    >
      <TabActive value={active}>{children}</TabActive>
    </div>
  )
}

function HeaderTabs({
  author,
  tab,
  places,
}: {
  author: string
  tab: AuthorTab
  places: AuthorPlaces
}) {
  const { tabs } = useHeaderSlots()
  if (!tabs) return null
  const props = (name: AuthorTab, label: string) => ({
    'aria-label': label,
    'aria-current': tab === name ? ('page' as const) : undefined,
    activeOptions: { exact: true },
    className: cn(
      'relative flex h-7 items-center justify-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium outline-none transition-colors duration-200 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50',
      tab === name ? 'text-foreground' : 'text-muted-foreground',
    ),
  })
  const postsLabel = (
    <>
      <Newspaper aria-hidden="true" className="size-4" />
      <span className="hidden sm:inline">Posts</span>
    </>
  )
  const search = { ...NO_FILTERS, ...places.posts?.filters }
  return createPortal(
    <nav
      aria-label="Author"
      className="relative grid shrink-0 grid-cols-2 rounded-lg bg-muted p-0.5"
    >
      <span aria-hidden="true" data-tab={tab} className="author-tab-pill" />
      {places.posts?.postId ? (
        <Link
          to="/a/$author/p/$postId"
          params={{ author, postId: places.posts.postId }}
          search={search}
          {...props('posts', 'Posts')}
        >
          {postsLabel}
        </Link>
      ) : (
        <Link to="/a/$author" params={{ author }} search={search} {...props('posts', 'Posts')}>
          {postsLabel}
        </Link>
      )}
      <Link
        to="/a/$author/media"
        params={{ author }}
        search={{ ...NO_MEDIA_FILTERS, ...places.media?.filters, open: undefined }}
        {...props('media', 'Media')}
      >
        <Images aria-hidden="true" className="size-4" />
        <span className="hidden sm:inline">Media</span>
      </Link>
    </nav>,
    tabs,
  )
}
