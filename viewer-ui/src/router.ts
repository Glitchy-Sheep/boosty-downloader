import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, createRoute, createRouter } from '@tanstack/react-router'
import type { RouterHistory } from '@tanstack/react-router'

import { AuthorsScreen, LoadError, LoadingAuthors, NotFound, ViewerShell } from '@/components/route-screens'
import { authorsQuery } from '@/lib/queries'

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

const routeTree = rootRoute.addChildren([authorsRoute])

export function createViewerRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({ routeTree, context: { queryClient }, history, defaultPendingMs: 0, defaultPendingMinMs: 0 })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createViewerRouter>
  }
}
