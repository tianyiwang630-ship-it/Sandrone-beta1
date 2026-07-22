import assert from 'node:assert/strict'
import test from 'node:test'

import {
  hasPendingPermission,
  isRetryInstructionValid,
  remainingPermissionSeconds,
} from '../src/permissionPrompt.ts'

test('permission countdown rounds up and never becomes negative', () => {
  assert.equal(remainingPermissionSeconds('2026-07-21T10:00:10Z', Date.parse('2026-07-21T10:00:00.100Z')), 10)
  assert.equal(remainingPermissionSeconds('2026-07-21T10:00:00Z', Date.parse('2026-07-21T10:00:01Z')), 0)
  assert.equal(remainingPermissionSeconds('invalid', Date.now()), 0)
})

test('retry instruction requires visible content', () => {
  assert.equal(isRetryInstructionValid('   '), false)
  assert.equal(isRetryInstructionValid('请改用全局安装'), true)
})

test('sidebar permission marker only appears for a pending request', () => {
  assert.equal(hasPendingPermission({ pendingPermission: { permission_id: 'perm-1' } }), true)
  assert.equal(hasPendingPermission({ pendingPermission: null }), false)
  assert.equal(hasPendingPermission(undefined), false)
})
