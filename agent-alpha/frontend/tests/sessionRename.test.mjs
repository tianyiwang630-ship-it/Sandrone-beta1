import assert from 'node:assert/strict'
import test from 'node:test'

import {
  mergeSessionDetail,
  replaceSessionSummary,
  validateSessionTitle,
} from '../src/sessionRename.ts'

const session = (id, title) => ({
  id,
  title,
  project_id: 'project',
  workspace_path: 'workspace',
  created_at: '2026-07-15T00:00:00',
  updated_at: '2026-07-15T00:00:00',
  message_count: 0,
  is_pinned: false,
  is_archived: false,
})

test('rename trims surrounding whitespace', () => {
  assert.equal(validateSessionTitle('  新名称  ', '旧名称'), '新名称')
})

test('empty, unchanged and oversized titles are rejected locally', () => {
  assert.equal(validateSessionTitle('   ', '旧名称'), null)
  assert.equal(validateSessionTitle('旧名称', '旧名称'), null)
  assert.equal(validateSessionTitle('x'.repeat(161), '旧名称'), null)
})

test('only the matching session is replaced even when titles are duplicated', () => {
  const sessions = [session('a', '相同'), session('b', '相同')]
  const updated = { ...sessions[1], title: '新名称' }

  assert.deepEqual(replaceSessionSummary(sessions, updated), [sessions[0], updated])
})

test('updating the selected summary preserves its loaded messages', () => {
  const detail = { ...session('a', '旧名称'), messages: [{ role: 'user', content: '你好' }] }
  const updated = { ...session('a', '新名称'), updated_at: '2026-07-15T00:01:00' }

  assert.deepEqual(mergeSessionDetail(detail, updated), { ...detail, ...updated })
  assert.deepEqual(detail.messages, [{ role: 'user', content: '你好' }])
})

test('an unrelated selected detail is not changed', () => {
  const detail = { ...session('a', 'A'), messages: [] }

  assert.equal(mergeSessionDetail(detail, session('b', 'B2')), detail)
})
