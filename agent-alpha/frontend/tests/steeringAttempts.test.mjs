import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clearSteeringDraftAttempt,
  loadSteeringDraftAttempt,
  saveSteeringDraftAttempt,
  steeringDraftAttemptKey,
} from '../src/steeringAttempts.ts'

class MemoryStorage {
  values = new Map()

  get length() { return this.values.size }
  key(index) { return [...this.values.keys()][index] ?? null }
  getItem(key) { return this.values.get(key) ?? null }
  setItem(key, value) { this.values.set(key, String(value)) }
  removeItem(key) { this.values.delete(key) }
}

test('uncertain direct steer keeps its message ID across run changes and refreshes', () => {
  const storage = new MemoryStorage()
  const sessionId = 'session-a'
  const content = '继续处理第二批'
  const keyBeforeRunChange = steeringDraftAttemptKey(sessionId, content)

  saveSteeringDraftAttempt(storage, sessionId, content, 'message-1')

  assert.equal(steeringDraftAttemptKey(sessionId, content), keyBeforeRunChange)
  assert.equal(loadSteeringDraftAttempt(storage, sessionId, content), 'message-1')
  assert.equal(loadSteeringDraftAttempt(storage, 'session-b', content), null)
})

test('confirmed or rejected attempt clears so a later intentional repeat gets a new ID', () => {
  const storage = new MemoryStorage()
  saveSteeringDraftAttempt(storage, 'session-a', '继续处理第二批', 'message-1')

  clearSteeringDraftAttempt(storage, 'session-a', '继续处理第二批', 'message-1')

  assert.equal(loadSteeringDraftAttempt(storage, 'session-a', '继续处理第二批'), null)
})

test('legacy run-scoped retry marker migrates to the session-scoped marker', () => {
  const storage = new MemoryStorage()
  const legacyKey = 'sandrone:steer-attempt:session-a:old-run'
  storage.setItem(legacyKey, JSON.stringify({ content: '继续处理第二批', messageId: 'message-1' }))

  assert.equal(loadSteeringDraftAttempt(storage, 'session-a', '继续处理第二批'), 'message-1')
  assert.equal(storage.getItem(legacyKey), null)
  assert.equal(loadSteeringDraftAttempt(storage, 'session-a', '继续处理第二批'), 'message-1')
})
