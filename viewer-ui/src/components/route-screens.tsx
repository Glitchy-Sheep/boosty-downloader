import { useQueryErrorResetBoundary, useSuspenseQuery } from '@tanstack/react-query'
import { Outlet, useLocation, useRouter } from '@tanstack/react-router'
import { useEffect } from 'react'

import { AppShell } from '@/components/app-shell'
import { AuthorsPage } from '@/components/authors-page'
import { ApiError } from '@/lib/api'
import { authorsQuery } from '@/lib/queries'

export function ViewerShell() {
  const pathname = useLocation({ select: location => location.pathname })
  return <AppShell isAuthorsPage={pathname === '/'}><Outlet /></AppShell>
}

export function LoadingAuthors() {
  return <p role="status" className="mx-auto max-w-[1180px] p-8 text-muted-foreground">Loading authors...</p>
}

export function LoadError({ error }: { error: unknown }) {
  const router = useRouter()
  const { reset } = useQueryErrorResetBoundary()
  useEffect(reset, [reset])
  const message = error instanceof ApiError ? error.message : 'Could not load the library.'
  return (
    <div className="mx-auto max-w-[1180px] p-8">
      <p role="alert">{message}</p>
      <button type="button" onClick={() => void router.invalidate()} className="mt-4 rounded-md border px-4 py-2 outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50">
        Try again
      </button>
    </div>
  )
}

export function NotFound() {
  return (
    <div className="mx-auto max-w-[1180px] p-8">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <a href="/" className="mt-4 inline-block rounded-sm text-primary underline outline-none focus-visible:ring-3 focus-visible:ring-ring/50">Back to authors</a>
    </div>
  )
}

export function AuthorsScreen() {
  const { data } = useSuspenseQuery(authorsQuery())
  return <AuthorsPage authors={data} />
}
