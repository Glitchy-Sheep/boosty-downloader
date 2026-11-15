import { expect, test, vi } from 'vitest'

import {
  createFileActionController,
  fileActionKey,
  type FileActionIdentity,
} from '@/lib/file-action-controller'

const identity: FileActionIdentity = {
  author: 'author',
  kind: 'media',
  id: 'piece',
  action: 'open',
}

test('deduplicates in-flight actions, keeping authors, targets and app instances independent', async () => {
  let finish = () => {}
  const response = new Promise<void>((resolve) => {
    finish = resolve
  })
  const operation = vi.fn(() => response)
  const accepted = vi.fn()
  const controller = createFileActionController()
  const listener = vi.fn()
  const unsubscribe = controller.subscribe(listener)
  const first = controller.run(identity, operation, accepted)
  await controller.run({ ...identity }, operation, accepted)
  const otherAuthor = controller.run({ ...identity, author: 'other' }, operation)
  const otherTarget = controller.run({ ...identity, kind: 'post' }, operation)
  const reveal = controller.run({ ...identity, action: 'reveal' }, operation)
  const otherApp = createFileActionController().run(identity, operation)
  expect(operation).toHaveBeenCalledTimes(5)
  expect(accepted).toHaveBeenCalledTimes(1)
  expect(controller.getSnapshot().pending.size).toBe(4)
  expect(controller.getSnapshot().pending.has(fileActionKey(identity))).toBe(true)
  finish()
  await Promise.all([first, otherAuthor, otherTarget, reveal, otherApp])
  expect(controller.getSnapshot().pending.size).toBe(0)
  unsubscribe()
  listener.mockClear()
  await controller.run(identity, async () => {})
  expect(listener).not.toHaveBeenCalled()
})

test('always releases pending and preserves a readable persistent failure', async () => {
  const controller = createFileActionController()
  await controller.run(identity, async () => {
    throw new Error('<script>no app</script>')
  })
  expect(controller.getSnapshot().pending.size).toBe(0)
  expect(controller.getSnapshot().notice).toEqual({
    kind: 'error',
    message: '<script>no app</script>',
  })
  await controller.run(identity, async () => {})
  expect(controller.getSnapshot().notice?.message).toBe('<script>no app</script>')
  const operation = vi.fn(async () => {})
  await controller.run(identity, operation, () => {
    throw 'unknown failure'
  })
  expect(operation).not.toHaveBeenCalled()
  expect(controller.getSnapshot().notice?.message).toBe('The file action failed.')
  expect(controller.getSnapshot().pending.size).toBe(0)
  controller.dismissNotice()
  expect(controller.getSnapshot().notice).toBeNull()
})

test('capability retries clear only their own notice and old dialogs cannot clear the active host', () => {
  const controller = createFileActionController()
  controller.clearCapabilitiesError()
  controller.showNotice({ kind: 'error', source: 'capabilities', message: 'Could not load' })
  controller.clearCapabilitiesError()
  expect(controller.getSnapshot().notice).toBeNull()
  controller.showNotice({ kind: 'path', path: '/library/file', message: 'Path copied' })
  controller.clearCapabilitiesError()
  expect(controller.getSnapshot().notice?.kind).toBe('path')
  controller.showNotice({ kind: 'error', message: 'Native open failed' })
  controller.clearCapabilitiesError()
  expect(controller.getSnapshot().notice?.message).toBe('Native open failed')
  const oldHost = document.createElement('div')
  const newHost = document.createElement('div')
  controller.setNoticeHost(oldHost)
  controller.setNoticeHost(newHost)
  controller.clearNoticeHost(oldHost)
  expect(controller.getSnapshot().noticeHost).toBe(newHost)
  controller.clearNoticeHost(newHost)
  expect(controller.getSnapshot().noticeHost).toBeNull()
})
