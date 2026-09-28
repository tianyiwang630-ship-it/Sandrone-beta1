import assert from 'node:assert/strict'
import test from 'node:test'

import { buildChatTurns } from '../src/chatTurns.ts'

const toolCall = (id, name, argumentsValue = {}) => ({
  role: 'assistant',
  content: null,
  tool_calls: [{ id, type: 'function', function: { name, arguments: JSON.stringify(argumentsValue) } }],
})

test('subagent result links back to its delegation tool even after a later user message', () => {
  const turns = buildChatTurns([
    { role: 'user', content: '帮我检查项目' },
    toolCall('call-create', 'subagent_create', { task_name: '检查' }),
    { role: 'tool', tool_call_id: 'call-create', content: JSON.stringify({ message_id: 'mail-create', target_id: 'agent-a' }) },
    { role: 'user', content: '直接告诉我目前进度' },
    {
      role: 'user',
      content: '[异步子 agent 结果：agent agent-a（检查）执行 ID run-a；对应委托消息 ["mail-create"]]\n检查完成。',
      source: 'subagent_result',
      source_agent_id: 'agent-a',
      reply_to: ['mail-create'],
      message_id: 'mail-result',
    },
    { role: 'assistant', content: '检查已完成。' },
  ])

  assert.equal(turns.length, 2)
  assert.equal(turns[0].user?.content, '帮我检查项目')
  assert.equal(turns[1].user?.content, '直接告诉我目前进度')
  assert.equal(turns[0].steps.at(-1)?.related_tool_call_id, 'call-create')
  assert.equal(turns[1].steps.some((message) => message.message_id === 'mail-result'), false)
})

test('messages from a subagent without a receipt match stay out of user turns', () => {
  const turns = buildChatTurns([
    { role: 'user', content: '开始' },
    { role: 'user', content: '同伴消息', source: 'agent', source_agent_id: 'agent-b', message_id: 'message-b' },
  ])

  assert.equal(turns.length, 1)
  assert.equal(turns[0].user?.content, '开始')
  assert.equal(turns[0].steps[0].content, '同伴消息')
})
