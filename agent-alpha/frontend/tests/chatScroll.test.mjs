import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clampScrollTop,
  isCurrentSessionRequest,
  readSessionScrollTop,
  removeSessionScrollTop,
  withoutSession,
  writeSessionScrollTop,
} from '../src/chatScroll.ts'

const memoryStorage = () => {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

test('each session keeps an independent position, including an explicit top position', () => {
  const storage = memoryStorage()
  writeSessionScrollTop(storage, 'long', 1280.5)
  writeSessionScrollTop(storage, 'short', 0)

  assert.equal(readSessionScrollTop(storage, 'long'), 1280.5)
  assert.equal(readSessionScrollTop(storage, 'short'), 0)
})

test('restored positions are clamped only when the rendered session is shorter', () => {
  assert.equal(clampScrollTop(800, 2000, 600), 800)
  assert.equal(clampScrollTop(800, 500, 600), 0)
  assert.equal(clampScrollTop(800, 1000, 600), 400)
})

test('corrupt, negative, infinite and unavailable storage safely fall back to top', () => {
  const corruptStorage = {
    getItem: () => '{not-json',
    setItem: () => { throw new Error('blocked') },
    removeItem: () => { throw new Error('blocked') },
  }
  assert.equal(readSessionScrollTop(corruptStorage, 'broken'), 0)
  assert.equal(readSessionScrollTop(null, 'missing'), 0)

  const storage = memoryStorage()
  writeSessionScrollTop(storage, 'negative', -1)
  writeSessionScrollTop(storage, 'infinite', Number.POSITIVE_INFINITY)
  assert.equal(readSessionScrollTop(storage, 'negative'), 0)
  assert.equal(readSessionScrollTop(storage, 'infinite'), 0)
  assert.doesNotThrow(() => writeSessionScrollTop(corruptStorage, 'blocked', 10))
  assert.doesNotThrow(() => removeSessionScrollTop(corruptStorage, 'blocked'))
})

test('deleting a session clears both persisted and in-memory state without touching neighbours', () => {
  const storage = memoryStorage()
  writeSessionScrollTop(storage, 'a', 10)
  writeSessionScrollTop(storage, 'b', 20)
  removeSessionScrollTop(storage, 'a')

  const positions = withoutSession({ a: 10, b: 20 }, 'a')
  assert.equal(readSessionScrollTop(storage, 'a'), 0)
  assert.equal(readSessionScrollTop(storage, 'b'), 20)
  assert.deepEqual(positions, { b: 20 })
})

test('a stale detail response cannot replace a newer request or another session', () => {
  assert.equal(isCurrentSessionRequest('a', 'a', 3, 3), true)
  assert.equal(isCurrentSessionRequest('a', 'a', 3, 2), false)
  assert.equal(isCurrentSessionRequest('b', 'a', 3, 3), false)
})

test('appended content never changes the saved top even when it was the old bottom', () => {
  const savedTop = 400
  assert.equal(clampScrollTop(savedTop, 1000, 600), 400)
  assert.equal(clampScrollTop(savedTop, 1800, 600), 400)
})

test('atomic handoff removes the live run from the render state without disturbing other sessions', () => {
  const running = withoutSession({ a: { requestId: 'done' }, b: { requestId: 'active' } }, 'a')
  assert.deepEqual(running, { b: { requestId: 'active' } })
})
