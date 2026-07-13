import assert from 'node:assert/strict'
import test from 'node:test'

import { excludeDeletedSessions } from '../src/sessionDeletion.ts'

test('deleting one of two sessions with the same title only removes the target id', () => {
  const sessions = [
    { id: 'older', title: 'new chat' },
    { id: 'newer', title: 'new chat' },
  ]

  const remaining = excludeDeletedSessions(sessions, new Set(['older']))

  assert.deepEqual(remaining, [{ id: 'newer', title: 'new chat' }])
})

test('a stale late response cannot put a deleted session back into the list', () => {
  const staleResponse = [
    { id: 'deleted', title: 'new chat' },
    { id: 'kept', title: 'other chat' },
  ]

  const remaining = excludeDeletedSessions(staleResponse, new Set(['deleted']))

  assert.deepEqual(remaining, [{ id: 'kept', title: 'other chat' }])
})

test('multiple deleted ids do not affect unrelated sessions', () => {
  const sessions = [
    { id: 'a', title: 'A' },
    { id: 'b', title: 'B' },
    { id: 'c', title: 'C' },
  ]

  const remaining = excludeDeletedSessions(sessions, new Set(['a', 'c']))

  assert.deepEqual(remaining, [{ id: 'b', title: 'B' }])
})
