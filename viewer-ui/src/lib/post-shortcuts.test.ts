import { afterEach, expect, test } from 'vitest'

import { acceptsPostShortcut, postShortcut } from '@/lib/post-shortcuts'

afterEach(() => document.body.replaceChildren())

function keyOn(target: Element = document.body, options: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent('keydown', {
    code: 'KeyJ',
    bubbles: true,
    cancelable: true,
    ...options,
  })
  target.dispatchEvent(event)
  return event
}

test.each([
  ['KeyJ', 'next'],
  ['KeyK', 'previous'],
  ['Slash', 'search'],
  ['KeyS', 'seen'],
  ['KeyF', 'favorite'],
  ['BracketLeft', 'sidebar'],
  ['Unidentified', null],
])('maps physical key %s to %s', (code, expected) => {
  expect(postShortcut(code)).toBe(expected)
})

test.each(['ctrlKey', 'metaKey', 'altKey', 'shiftKey', 'isComposing'] as const)(
  'leaves %s keyboard events to their owner',
  (flag) => {
    expect(acceptsPostShortcut(keyOn(document.body, { [flag]: true }), document)).toBe(false)
  },
)

test('honors prevented events and accepts repeated physical keys in both layouts', () => {
  const prevented = keyOn()
  prevented.preventDefault()
  expect(acceptsPostShortcut(prevented, document)).toBe(false)
  for (const key of ['j', 'о']) {
    const repeated = keyOn(document.body, { key, repeat: true })
    expect(postShortcut(repeated.code)).toBe('next')
    expect(acceptsPostShortcut(repeated, document)).toBe(true)
  }
})

test.each([
  '<input>',
  '<textarea></textarea>',
  '<select></select>',
  '<audio controls></audio>',
  '<video controls></video>',
  '<div role="textbox"><span>editing</span></div>',
  '<div role="combobox"><span>selection</span></div>',
  '<div contenteditable><span>editing</span></div>',
  '<div contenteditable="plaintext-only"><span>editing</span></div>',
])('ignores the focused keyboard owner %s', (html) => {
  document.body.innerHTML = html
  const target = document.body.querySelector('span') ?? document.body.firstElementChild
  expect(target).not.toBeNull()
  if (!target) throw new Error('Missing test target')
  expect(acceptsPostShortcut(keyOn(target), document)).toBe(false)
})

test.each(['button', 'a', 'div'])('allows reading shortcuts on ordinary %s elements', (tag) => {
  const target = document.createElement(tag)
  document.body.append(target)
  expect(acceptsPostShortcut(keyOn(target), document)).toBe(true)
})

test('an explicitly noneditable island can use reading shortcuts', () => {
  document.body.innerHTML =
    '<div contenteditable="true"><button contenteditable="false">Save</button></div>'
  const button = document.querySelector('button')
  if (!button) throw new Error('Missing button')
  expect(acceptsPostShortcut(keyOn(button), document)).toBe(true)
})

test.each([
  '<dialog open></dialog>',
  '<div role="dialog"></div>',
  '<div role="alertdialog"></div>',
  '<div role="menu"></div>',
])('an open dialog owns shortcuts even when the event target is outside: %s', (html) => {
  document.body.innerHTML = html
  expect(acceptsPostShortcut(keyOn(), document)).toBe(false)
})

test.each([
  '<dialog></dialog>',
  '<div role="dialog" hidden></div>',
  '<div role="dialog" aria-hidden="true"></div>',
  '<div role="dialog" data-state="closed"></div>',
  '<div inert><div role="dialog"></div></div>',
  '<div style="display:none"><div role="dialog"></div></div>',
  '<div role="dialog" style="visibility:hidden"></div>',
])('a closed or hidden dialog does not block the page: %s', (html) => {
  document.body.innerHTML = html
  expect(acceptsPostShortcut(keyOn(), document)).toBe(true)
})

test('a document target has no editing ownership', () => {
  const event = new KeyboardEvent('keydown', { code: 'Slash' })
  document.dispatchEvent(event)
  expect(acceptsPostShortcut(event, document)).toBe(true)
})
