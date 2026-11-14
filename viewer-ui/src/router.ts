import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, createRoute, createRouter, redirect } from '@tanstack/react-router'
import type { RouterHistory } from '@tanstack/react-router'

import { AuthorsScreen, LoadError, LoadingAuthors, NotFound, ViewerShell } from '@/components/route-screens'
import { EmptyPostList, LoadingAuthor, LoadingPost, PostsScreen, SelectedPost } from '@/components/posts-screen'
import { parseFilters } from '@/lib/filters'
import { authorQuery, authorsQuery, postQuery, postsQuery } from '@/lib/queries'
import { parseViewerSearch, stringifyViewerSearch } from '@/lib/url-search'

interface ViewerContext {
  queryClient: QueryClient
}

const rootRoute = createRootRouteWithContext<ViewerContext>()({
  component: ViewerShell,
  notFoundComponent: NotFound,
})

const authorsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  loader: ({ context }) => context.queryClient.ensureQueryData(authorsQuery()),
  component: AuthorsScreen,
  pendingComponent: LoadingAuthors,
  errorComponent: LoadError,
})

const authorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/a/$author',
  loader: ({ context, params }) => context.queryClient.ensureQueryData(authorQuery(params.author)),
  pendingComponent: LoadingAuthor,
  errorComponent: LoadError,
})

const postsRoute = createRoute({
  getParentRoute: () => authorRoute,
  id: '_posts',
  validateSearch: parseFilters,
  component: PostsScreen,
})

const postsIndexRoute = createRoute({
  getParentRoute: () => postsRoute,
  path: '/',
  loaderDeps: ({ search }) => search,
  loader: async ({ context, params, deps }) => {
    const posts = await context.queryClient.ensureQueryData(postsQuery(params.author, deps))
    const first = posts.rows[0]
    if (!first) return
    throw redirect({ to: '/a/$author/p/$postId', params: { author: params.author, postId: first.id }, search: deps, replace: true })
  },
  component: EmptyPostList,
  pendingComponent: LoadingPost,
  errorComponent: LoadError,
})

const postRoute = createRoute({
  getParentRoute: () => postsRoute,
  path: '/p/$postId',
  loader: ({ context, params }) => context.queryClient.ensureQueryData(postQuery(params.author, params.postId)),
  component: SelectedPost,
  pendingComponent: LoadingPost,
  errorComponent: LoadError,
})

const routeTree = rootRoute.addChildren([
  authorsRoute,
  authorRoute.addChildren([postsRoute.addChildren([postsIndexRoute, postRoute])]),
])

export function createViewerRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context: { queryClient },
    history,
    parseSearch: parseViewerSearch,
    stringifySearch: stringifyViewerSearch,
    defaultPendingMs: 0,
    defaultPendingMinMs: 0,
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createViewerRouter>
  }
}
