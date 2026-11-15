import { createContext, useContext } from 'react'

export type AuthorTab = 'posts' | 'media'

/** Retained panes keep their layout while only the selected tab accepts input. */
export const TabActive = createContext(true)

export function useTabActive(): boolean {
  return useContext(TabActive)
}

export function authorTab(pathname: string): AuthorTab {
  return /^\/a\/[^/]+\/media\/?$/.test(pathname) ? 'media' : 'posts'
}

export function isAuthorPosts(pathname: string, author: string): boolean {
  const root = `/a/${encodeURIComponent(author)}`
  return pathname === root || pathname === `${root}/` || pathname.startsWith(`${root}/p/`)
}
