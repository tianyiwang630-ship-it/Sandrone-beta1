import assert from 'node:assert/strict'
import test from 'node:test'

import {
  attachesLiveRunToTurn,
  displayedAssistantText,
  displayedProcessContent,
  formatRunFailureMessage,
  hasAssistantProcessText,
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

test('completed process presentation keeps assistant text visible', () => {
  const assistantWithTool = {
    ...toolCall('call-bash', 'bash'),
    content: '端口通了，jobsdb 页面也加载出来了。',
  }
  const items = mergeProcessPresentation([assistantWithTool, toolResult('call-bash')], [])

  assert.equal(hasAssistantProcessText(items), true)
})

test('tool-only process presentation does not force the process group open', () => {
  const items = mergeProcessPresentation([toolCall('call-bash', 'bash'), toolResult('call-bash')], [])

  assert.equal(hasAssistantProcessText(items), false)
})

test('assistant text is shown instead of being replaced by the tool label', () => {
  const assistantWithTool = {
    ...toolCall('call-bash', 'bash'),
    content: '端口通了，jobsdb 页面也加载出来了。',
  }

  assert.equal(displayedProcessContent(assistantWithTool, '调用工具: bash'), assistantWithTool.content)
})

test('tool label remains as the fallback when the assistant emitted no text', () => {
  assert.equal(displayedProcessContent(toolCall('call-bash', 'bash'), '调用工具: bash'), '调用工具: bash')
  assert.equal(
    displayedProcessContent({ ...toolCall('call-bash', 'bash'), content: '   ' }, '调用工具: bash'),
    '调用工具: bash',
  )
})

test('unexpected run failures use a generic runtime message', () => {
  assert.equal(
    formatRunFailureMessage({ requestId: 'req', startedAfterSeq: 0, error: 'boom' }),
    '运行失败：boom。已保留本轮已完成工具记录。',
  )
})

test('recoverable model failures keep recovery guidance', () => {
  assert.equal(
    formatRunFailureMessage({
      requestId: 'req',
      startedAfterSeq: 0,
      error: 'timeout',
      recoverable: true,
    }),
    '本轮模型请求暂未完成：timeout。现场已保存，可直接发送“继续”恢复。',
  )
})

test('context compaction failures keep compaction-specific guidance', () => {
  assert.equal(
    formatRunFailureMessage({
      requestId: 'req',
      startedAfterSeq: 0,
      error: 'too large',
      operation: 'compact',
    }),
    '上下文压缩失败：too large。原会话历史和模型上下文未改变。',
  )
})
