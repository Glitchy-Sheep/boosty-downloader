import { fireEvent } from '@testing-library/dom'
import { describe, expect, it, vi } from 'vitest'

import { postNavigation, preparePostLinks } from '@/lib/post-body-links'

describe('post body links', () => {
  it('rejects executable schemes and preserves safe external links', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<a href="javascript:alert(1)">bad</a><a href="data:text/html,bad">data</a><a href="https://example.com/post?q=1#part">web</a><a href="mailto:writer@example.com">mail</a>'
    preparePostLinks(root)
    const links = root.querySelectorAll('a')
    expect(links[0]).not.toHaveAttribute('href')
    expect(links[1]).not.toHaveAttribute('href')
    expect(links[2]).toHaveAttribute('href', 'https://example.com/post?q=1#part')
    expect(links[2]).toHaveAttribute('target', '_blank')
    expect(links[2]).toHaveAttribute('rel', 'noreferrer noopener')
    expect(links[3]).toHaveAttribute('href', 'mailto:writer@example.com')
  })

  it('routes an ordinary local post link with its own search and fragment', () => {
    const root = document.createElement('div')
    root.innerHTML = '<a href="/a/other/p/id?q=001&tag=own#section"><strong>post</strong></a>'
    const navigate = vi.fn()
    root.addEventListener('click', (event) => {
      navigate(postNavigation(event))
      event.preventDefault()
    })
    preparePostLinks(root)
    fireEvent.click(root.querySelector('strong')!)
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/a/other/p/id?q=001&tag=own#section')
    expect(root.querySelector('a')).not.toHaveAttribute('target')
  })

  it.each([
    { href: '/a/w/p/id', ctrlKey: true },
    { href: '/a/w/p/id', metaKey: true },
    { href: '/a/w/p/id', shiftKey: true },
    { href: '/a/w/p/id', altKey: true },
    { href: '/a/w/p/id', button: 1 },
    { href: '/a/w/p/id', target: '_blank' },
    { href: '/a/w/p/id', download: true },
    { href: '/media/w/a.pdf' },
    { href: 'https://example.com/a/w/p/id' },
    { href: '#part' },
  ])(
    'leaves browser handling intact for $href $target $button',
    ({ href, target, download, ...event }) => {
      const link = document.createElement('a')
      link.href = href
      if (target) link.target = target
      if (download) link.download = ''
      const navigate = vi.fn()
      link.addEventListener('click', (click) => {
        navigate(postNavigation(click))
        click.preventDefault()
      })
      fireEvent.click(link, event)
      expect(navigate).toHaveBeenCalledExactlyOnceWith(null)
    },
  )
})
