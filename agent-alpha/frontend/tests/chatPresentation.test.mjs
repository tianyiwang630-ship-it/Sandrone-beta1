import assert from 'node:assert/strict'
import test from 'node:test'

import {
  attachesLiveRunToTurn,
  buildToolPresentation,
  displayedAssistantText,
  displayedProcessContent,
  formatRunFailureMessage,
  hasAssistantProcessText,
  mergeActiveRunEvents,
  mergeProcessPresentation,
  processMessageKey,
} from '../src/chatPresentation.ts'

const toolCalls = (calls, content = null) => ({
  role: 'assistant',
  content,
  tool_calls: calls.map(({ id, name, arguments: argumentsValue = '{}' }) => ({
    id,
    type: 'function',
    function: { name, arguments: argumentsValue },
  })),
})

const toolCall = (id, name, argumentsValue = '{}', content = null) => (
  toolCalls([{ id, name, arguments: argumentsValue }], content)
)

const toolResult = (id, content = 'ok') => ({ role: 'tool', tool_call_id: id, content })
const entryEvent = (seq, entry) => ({ session_id: 'session', seq, entry })
const toolPresentation = (history, liveEvents = [], options = { isLive: false, runFinished: true }) => (
  buildToolPresentation(mergeProcessPresentation(history, liveEvents), options)
)

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

test('tool results pair with same-name calls by call id when results arrive out of order', () => {
  const calls = toolCalls([
    { id: 'bash-first', name: 'bash', arguments: '{"command":"first"}' },
    { id: 'bash-second', name: 'bash', arguments: '{"command":"second"}' },
  ])
  const presentation = toolPresentation([
    calls,
    toolResult('bash-second', 'second output'),
    toolResult('bash-first', 'first output'),
  ])

  assert.deepEqual(
    presentation.toolCalls.map((call) => ({
      name: call.name,
      arguments: call.arguments,
      output: call.output,
      outputState: call.outputState,
    })),
    [
      {
        name: 'bash',
        arguments: '{\n  "command": "first"\n}',
        output: 'first output',
        outputState: 'received',
      },
      {
        name: 'bash',
        arguments: '{\n  "command": "second"\n}',
        output: 'second output',
        outputState: 'received',
      },
    ],
  )
  assert.equal(presentation.unpairedResults.length, 0)
  assert.equal(presentation.otherItems.length, 0)
})

test('live and history copies of the same tool entries render only once', () => {
  const call = toolCall('read-1', 'read', '{"path":"README.md"}')
  const result = toolResult('read-1', 'read output')
  const presentation = toolPresentation(
    [call, result],
    [entryEvent(11, call), entryEvent(12, result)],
    { isLive: true, runFinished: false },
  )

  assert.equal(presentation.toolCalls.length, 1)
  assert.equal(presentation.toolCalls[0].name, 'read')
  assert.equal(presentation.toolCalls[0].output, 'read output')
  assert.equal(presentation.toolCalls[0].outputState, 'received')
})

test('tool arguments are formatted as JSON and preserve malformed source text', () => {
  const presentation = toolPresentation([
    toolCalls([
      { id: 'valid', name: 'read', arguments: '{"path":"a.md","line":2}' },
      { id: 'empty', name: 'list', arguments: '' },
      { id: 'missing', name: 'clock', arguments: null },
      { id: 'malformed', name: 'bash', arguments: '{command: broken' },
    ]),
    toolResult('valid'),
    toolResult('empty'),
    toolResult('missing'),
    toolResult('malformed'),
  ])

  assert.deepEqual(
    presentation.toolCalls.map((call) => call.arguments),
    [
      '{\n  "path": "a.md",\n  "line": 2\n}',
      '{}',
      '{}',
      '{command: broken',
    ],
  )
})

test('tool cards distinguish running, missing, empty, received, and failed outputs', () => {
  const running = toolPresentation(
    [toolCall('running', 'bash')],
    [],
    { isLive: true, runFinished: false },
  ).toolCalls[0]
  const missing = toolPresentation(
    [toolCall('missing', 'bash')],
    [],
    { isLive: true, runFinished: true },
  ).toolCalls[0]
  const completed = toolPresentation([
    toolCalls([
      { id: 'empty', name: 'bash' },
      { id: 'received', name: 'bash' },
      { id: 'failed', name: 'bash' },
    ]),
    toolResult('empty', ''),
    toolResult('received', 'normal output'),
    toolResult('failed', '执行失败：权限不足'),
  ]).toolCalls

  assert.deepEqual(
    [
      { output: running.output, outputState: running.outputState },
      { output: missing.output, outputState: missing.outputState },
      ...completed.map((call) => ({ output: call.output, outputState: call.outputState })),
    ],
    [
      { output: '执行中…', outputState: 'running' },
      { output: '未收到输出', outputState: 'missing' },
      { output: '无输出', outputState: 'empty' },
      { output: 'normal output', outputState: 'received' },
      { output: '执行失败：权限不足', outputState: 'received' },
    ],
  )
})

test('assistant text before a tool call is retained separately from the tool card', () => {
  const presentation = toolPresentation([
    toolCall('read-1', 'read', '{"path":"notes.md"}', '我先读取笔记，再给你结论。'),
    toolResult('read-1', '笔记内容'),
  ])
  const call = presentation.toolCalls[0]

  assert.equal(call.assistantText, '我先读取笔记，再给你结论。')
  assert.equal(call.name, 'read')
  assert.equal(call.arguments, '{\n  "path": "notes.md"\n}')
  assert.equal(call.output, '笔记内容')
  assert.equal(Object.hasOwn(call, 'id'), false)
  assert.equal(Object.hasOwn(call, 'toolCallId'), false)
})

test('a historical result without its call remains available as a separate tool output', () => {
  const presentation = toolPresentation([toolResult('missing-call', '保留的历史输出')])

  assert.equal(presentation.toolCalls.length, 0)
  assert.equal(presentation.unpairedResults.length, 1)
  assert.match(JSON.stringify(presentation.unpairedResults[0]), /保留的历史输出/)
})
