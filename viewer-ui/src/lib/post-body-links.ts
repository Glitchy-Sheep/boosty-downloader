const SAFE_PROTOCOLS = new Set(['http:', 'https:', 'mailto:'])

function safeLink(href: string): URL | null {
  try {
    const url = new URL(href, location.href)
    return SAFE_PROTOCOLS.has(url.protocol) ? url : null
  } catch { return null }
}

/** Unsafe links keep their text; external links leave the saved post open. */
export function preparePostLinks(root: HTMLElement): void {
  for (const link of root.querySelectorAll<HTMLAnchorElement>('a[href]')) {
    const url = safeLink(link.getAttribute('href') ?? '')
    if (!url) { link.removeAttribute('href'); continue }
    if (url.origin !== location.origin) {
      link.target = '_blank'
      link.rel = 'noreferrer noopener'
    }
  }
}

/** Only ordinary local post navigation belongs to the application router. */
export function postNavigation(event: MouseEvent): string | null {
  if (event.defaultPrevented || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return null
  if (!(event.target instanceof Element)) return null
  const link = event.target.closest<HTMLAnchorElement>('a[href]')
  if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return null
  const url = safeLink(link.href)
  if (!url || url.origin !== location.origin || !/^\/a\/[^/]+\/p\/[^/]+\/?$/.test(url.pathname)) return null
  return `${url.pathname}${url.search}${url.hash}`
}
