import assert from 'node:assert/strict'
import test from 'node:test'

import {
  emptySessionMessageQueue,
  enqueuePriorityMessage,
  enqueueQueuedMessage,
  moveQueuedMessage,
  pauseMessageQueue,
  resumeMessageQueue,
  takeNextQueuedMessage,
  withdrawQueuedMessage,
} from '../src/messageQueue.ts'

const message = (id, content = id) => ({ id, content })

test('normal messages run in FIFO order', () => {
  let queue = enqueueQueuedMessage(emptySessionMessageQueue(), message('a'))
  queue = enqueueQueuedMessage(queue, message('b'))

  const first = takeNextQueuedMessage(queue)
  const second = takeNextQueuedMessage(first.queue)

  assert.equal(first.message?.id, 'a')
  assert.equal(second.message?.id, 'b')
})

test('withdraw removes only the selected duplicate message', () => {
  let queue = enqueueQueuedMessage(emptySessionMessageQueue(), message('a', 'same'))
  queue = enqueueQueuedMessage(queue, message('b', 'same'))

  queue = withdrawQueuedMessage(queue, 'a')

  assert.deepEqual(queue.items.map((item) => item.id), ['b'])
})

test('withdrawing the last message also clears the paused state', () => {
  let queue = enqueueQueuedMessage(emptySessionMessageQueue(), message('a'))
  queue = pauseMessageQueue(queue)

  queue = withdrawQueuedMessage(queue, 'a')

  assert.deepEqual(queue, emptySessionMessageQueue())
})

test('paused queue does not yield a message until resumed', () => {
  const paused = pauseMessageQueue(enqueueQueuedMessage(emptySessionMessageQueue(), message('a')))

  assert.equal(takeNextQueuedMessage(paused).message, null)
  assert.equal(takeNextQueuedMessage(resumeMessageQueue(paused)).message?.id, 'a')
})

test('dragging supports first-to-last and last-to-first moves', () => {
  let queue = emptySessionMessageQueue()
  for (const id of ['a', 'b', 'c']) queue = enqueueQueuedMessage(queue, message(id))

  queue = moveQueuedMessage(queue, 'a', 'c', 'after')
  assert.deepEqual(queue.items.map((item) => item.id), ['b', 'c', 'a'])

  queue = moveQueuedMessage(queue, 'a', 'b', 'before')
  assert.deepEqual(queue.items.map((item) => item.id), ['a', 'b', 'c'])
})

test('invalid and self drag operations are no-ops', () => {
  let queue = enqueueQueuedMessage(emptySessionMessageQueue(), message('a'))
  queue = enqueueQueuedMessage(queue, message('b'))

  assert.equal(moveQueuedMessage(queue, 'a', 'a', 'after'), queue)
  assert.equal(moveQueuedMessage(queue, 'missing', 'b', 'before'), queue)
})

test('priority messages stay ahead of the old queue and preserve send order', () => {
  let queue = enqueueQueuedMessage(emptySessionMessageQueue(), message('old-a'))
  queue = enqueueQueuedMessage(queue, message('old-b'))
  queue = pauseMessageQueue(queue)
  queue = enqueuePriorityMessage(queue, message('new-a'))
  queue = enqueuePriorityMessage(queue, message('new-b'))

  assert.equal(queue.paused, false)
  assert.deepEqual(queue.items.map((item) => item.id), ['new-a', 'new-b', 'old-a', 'old-b'])
})

test('manual reorder becomes the authoritative order', () => {
  let queue = enqueueQueuedMessage(emptySessionMessageQueue(), message('old'))
  queue = enqueuePriorityMessage(queue, message('priority'))
  queue = moveQueuedMessage(queue, 'priority', 'old', 'after')

  assert.deepEqual(queue.items.map((item) => item.id), ['old', 'priority'])
  assert.equal(takeNextQueuedMessage(queue).message?.id, 'old')
})
