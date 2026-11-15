import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
} from '@tanstack/react-router'
import type { RouterHistory } from '@tanstack/react-router'

import { AuthorShell } from '@/components/author-shell'

import {
  AuthorsScreen,
  LoadError,
  LoadingAuthors,
  NotFound,
  ViewerShell,
} from '@/components/route-screens'
import { LoadingAuthor } from '@/components/posts-screen'
import { parseFilters } from '@/lib/filters'
import { waitForAuthorMarks } from '@/lib/mark-navigation'
import { parseMediaSearch, toMediaFilters } from '@/lib/media-filters'
import { authorQuery, authorsQuery, mediaQuery, postQuery, postsQuery } from '@/lib/queries'
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
  component: AuthorShell,
  pendingComponent: LoadingAuthor,
  errorComponent: LoadError,
})

const postsRoute = createRoute({
  getParentRoute: () => authorRoute,
  id: '_posts',
  validateSearch: parseFilters,
  loaderDeps: ({ search }) => search,
  loader: async ({ context, params, deps, cause, abortController }) => {
    if (cause !== 'enter') return
    await waitForAuthorMarks(context.queryClient, params.author, abortController.signal)
    return context.queryClient.fetchQuery(postsQuery(params.author, deps))
  },
})

const postsIndexRoute = createRoute({
  getParentRoute: () => postsRoute,
  path: '/',
  loaderDeps: ({ search }) => search,
  loader: async ({ context, params, deps, abortController }) => {
    await waitForAuthorMarks(context.queryClient, params.author, abortController.signal)
    const posts = await context.queryClient.fetchQuery(postsQuery(params.author, deps))
    const first = posts.rows[0]
    if (!first) return
    throw redirect({
      to: '/a/$author/p/$postId',
      params: { author: params.author, postId: first.id },
      search: deps,
      replace: true,
    })
  },
})

const postRoute = createRoute({
  getParentRoute: () => postsRoute,
  path: '/p/$postId',
  loader: ({ context, params }) =>
    context.queryClient.fetchQuery(postQuery(params.author, params.postId)),
})

const mediaRoute = createRoute({
  getParentRoute: () => authorRoute,
  path: '/media',
  validateSearch: parseMediaSearch,
  loaderDeps: ({ search }) => toMediaFilters(search),
  loader: async ({ context, params, location, abortController }) => {
    await waitForAuthorMarks(context.queryClient, params.author, abortController.signal)
    return context.queryClient.fetchQuery(
      mediaQuery(params.author, parseMediaSearch(location.search)),
    )
  },
})

const routeTree = rootRoute.addChildren([
  authorsRoute,
  authorRoute.addChildren([postsRoute.addChildren([postsIndexRoute, postRoute]), mediaRoute]),
])

export function createViewerRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context: { queryClient },
    ...(history ? { history } : {}),
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
