import assert from 'node:assert/strict'
import test from 'node:test'

import {
  attachesLiveRunToTurn,
  displayedAssistantText,
  mergeActiveRunEvents,
  mergeProcessPresentation,
  processMessageKey,
} from '../src/chatPresentation.ts'

const toolCall = (id, name) => ({
  role: 'assistant',
  content: null,
  tool_calls: [{ id, type: 'function', function: { name, arguments: '{}' } }],
})

const toolResult = (id, content = 'ok') => ({ role: 'tool', tool_call_id: id, content })
const entryEvent = (seq, entry) => ({ session_id: 'session', seq, entry })

test('partial history and live events become one deduplicated process collection', () => {
  const bashCall = toolCall('call-bash', 'bash')
  const bashResult = toolResult('call-bash')
  const readCall = toolCall('call-read', 'read')
  const readResult = toolResult('call-read')
  const items = mergeProcessPresentation(
    [bashCall, bashResult],
    [
      entryEvent(1, bashCall),
      entryEvent(2, bashResult),
      entryEvent(3, readCall),
      entryEvent(4, readResult),
    ],
  )

  assert.equal(items.length, 4)
  assert.deepEqual(items.map((item) => item.key), [
    processMessageKey(bashCall),
    processMessageKey(bashResult),
    processMessageKey(readCall),
    processMessageKey(readResult),
  ])
})

test('repeated calls of the same tool remain distinct when call ids differ', () => {
  const items = mergeProcessPresentation([], [
    entryEvent(1, toolCall('bash-1', 'bash')),
    entryEvent(2, toolResult('bash-1')),
    entryEvent(3, toolCall('bash-2', 'bash')),
    entryEvent(4, toolResult('bash-2')),
  ])

  assert.equal(items.length, 4)
  assert.equal(new Set(items.map((item) => item.key)).size, 4)
})

test('active event merging retains streamed text removed by backend compaction', () => {
  const delta = { session_id: 'session', seq: 10, type: 'assistant_delta', event: { content: '回答' } }
  const tool = entryEvent(11, toolCall('read-1', 'read'))

  assert.deepEqual(mergeActiveRunEvents([delta, tool], [tool]), [delta, tool])
})

test('only the last chat turn receives live state', () => {
  assert.equal(attachesLiveRunToTurn('chat', 1, 2), true)
  assert.equal(attachesLiveRunToTurn('chat', 0, 2), false)
  assert.equal(attachesLiveRunToTurn('compact', 1, 2), false)
})

test('streamed answer remains authoritative until the final snapshot takes over', () => {
  assert.equal(displayedAssistantText('流式回答', ''), '流式回答')
  assert.equal(displayedAssistantText('', '正式回答'), '正式回答')
})
