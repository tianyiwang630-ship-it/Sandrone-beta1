import type { Message, SessionEvent } from './types'

export function mergeVisibleChatMessages(history: Message[], pending: Message[], events: SessionEvent[]) {
  const historyIds = new Set(history.map((message) => message.message_id).filter(Boolean))
  const receivedIds = new Set(
    events
      .map((event) => event.entry?._message_id)
      .filter((id): id is string => typeof id === 'string' && Boolean(id)),
  )
  const visiblePending = pending
    .filter((message) => !message.message_id || !historyIds.has(message.message_id))
    .map((message) => message.message_id && receivedIds.has(message.message_id)
      ? { ...message, delivery_status: 'received' as const }
      : message)
  return [...history, ...visiblePending]
}

export function isCollaborationMessage(message: Partial<Message>) {
  const source = message.source || message._source
  return message.role === 'user'
    && (source === 'agent' || source === 'subagent_result' || Boolean(message.source_agent_id || message._sender_id))
}

export function collaborationMessageText(message: Message) {
  const content = messageContentText(message)
  const lines = content.split('\n')
  if (message.source === 'agent' && lines[0].startsWith('[协作消息：')) return lines.slice(1).join('\n')
  if (message.source === 'subagent_result' && lines[0].startsWith('[异步子 agent 结果：')) return lines.slice(1).join('\n')
  return content
}

export type ProcessPresentationItem =
  | { key: string; kind: 'message'; message: Message }
  | { key: string; kind: 'event'; event: SessionEvent }

export interface FailedRunSnapshot {
  requestId: string
  startedAfterSeq: number
  error: string
  operation?: 'chat' | 'compact'
  recoverable?: boolean
}

export type ToolOutputState = 'running' | 'missing' | 'empty' | 'received'

export interface ToolPresentation {
  key: string
  name: string
  assistantText: string
  arguments: string
  output: string
  outputState: ToolOutputState
  collaborationMessages: Message[]
}

export interface ToolResultPresentation {
  key: string
  output: string
  outputState: 'empty' | 'received'
}

export interface ToolProcessPresentation {
  toolCalls: ToolPresentation[]
  unpairedResults: ToolResultPresentation[]
  otherItems: ProcessPresentationItem[]
}

export interface BuildToolPresentationOptions {
  isLive: boolean
  runFinished: boolean
}

function stableHash(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

function toolCallId(call: Record<string, unknown>) {
  return String(call.id || '')
}

export function toolCallName(call: Record<string, unknown>) {
  const fn = call.function
  if (fn && typeof fn === 'object' && 'name' in fn) {
    return String((fn as { name?: unknown }).name || 'tool')
  }
  return String(call.name || call.type || 'tool')
}

export function processMessageKey(message: Message) {
  if (Array.isArray(message.tool_calls) && message.tool_calls.length > 0) {
    const callIds = message.tool_calls.map(toolCallId).filter(Boolean)
    if (callIds.length === message.tool_calls.length) return `assistant-tools:${callIds.join(',')}`
  }
  if (message.role === 'tool' && message.tool_call_id) return `tool-result:${message.tool_call_id}`
  return `message:${message.role}:${stableHash(JSON.stringify(message))}`
}

function eventKey(event: SessionEvent) {
  const seq = Number(event.seq)
  if (Number.isFinite(seq) && seq > 0) return `event:${event.session_id || ''}:${seq}`
  return `event:${stableHash(JSON.stringify(event))}`
}

function eventMessage(event: SessionEvent): Message | null {
  const entry = event.entry
  if (!entry || typeof entry !== 'object') return null
  if (typeof entry.role !== 'string') return null
  const message = entry as unknown as Message
  if (message.role === 'tool') return message
  if (Array.isArray(message.tool_calls) && message.tool_calls.length > 0) return message
  if (isCollaborationMessage(message)) {
    return {
      ...message,
      source: message.source || String(message._source || ''),
      source_agent_id: message.source_agent_id || String(message._sender_id || '') || null,
      reply_to: Array.isArray(message.reply_to) ? message.reply_to : Array.isArray(message._reply_to) ? message._reply_to : [],
    }
  }
  return null
}

export function mergeProcessPresentation(
  historySteps: Message[],
  visibleLiveEvents: SessionEvent[],
): ProcessPresentationItem[] {
  const items: ProcessPresentationItem[] = []
  const seen = new Set<string>()

  for (const event of visibleLiveEvents) {
    const message = eventMessage(event)
    const key = message ? processMessageKey(message) : eventKey(event)
    if (seen.has(key)) continue
    seen.add(key)
    items.push(message ? { key, kind: 'message', message } : { key, kind: 'event', event })
  }

  for (const message of historySteps) {
    const key = processMessageKey(message)
    if (seen.has(key)) continue
    seen.add(key)
    items.push({ key, kind: 'message', message })
  }

  return items
}

export function hasAssistantProcessText(items: ProcessPresentationItem[]) {
  return items.some(
    (item) =>
      item.kind === 'message'
      && Array.isArray(item.message.tool_calls)
      && typeof item.message.content === 'string'
      && item.message.content.trim().length > 0,
  )
}

export function displayedProcessContent(message: Message, fallback: string) {
  const content = message.content
  if (typeof content === 'string') return content.trim() ? content : fallback
  if (content == null) return fallback
  return JSON.stringify(content, null, 2)
}

function messageContentText(message: Message) {
  const content = message.content
  if (typeof content === 'string') return content
  if (content == null) return ''
  return JSON.stringify(content, null, 2) || String(content)
}

function formatToolArguments(call: Record<string, unknown>) {
  const fn = call.function
  const rawArguments = fn && typeof fn === 'object'
    ? (fn as Record<string, unknown>).arguments
    : call.arguments

  if (typeof rawArguments === 'string') {
    if (!rawArguments.trim()) return '{}'
    try {
      return JSON.stringify(JSON.parse(rawArguments), null, 2)
    } catch {
      return rawArguments
    }
  }
  if (rawArguments == null) return '{}'
  return JSON.stringify(rawArguments, null, 2) || '{}'
}

function outputPresentation(content: unknown): { output: string; outputState: 'empty' | 'received' } {
  const output = typeof content === 'string'
    ? content
    : content == null
      ? ''
      : JSON.stringify(content, null, 2) || String(content)
  if (!output.trim()) return { output: '无输出', outputState: 'empty' }
  return { output, outputState: 'received' }
}

function objectValue(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  if (typeof value !== 'string') return null
  try {
    const parsed: unknown = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    return null
  }
}

function toolCallTargetId(call: Record<string, unknown>) {
  const fn = call.function
  const args = fn && typeof fn === 'object' && 'arguments' in fn
    ? objectValue(fn.arguments)
    : objectValue(call.arguments)
  return typeof args?.target_id === 'string' ? args.target_id : null
}

function isToolLifecycleEvent(item: ProcessPresentationItem) {
  if (item.kind !== 'event') return false
  const payload = item.event.event || item.event.entry || item.event
  const type = String(item.event.type || (payload as Record<string, unknown>).type || '')
  return type === 'tool_execution_started'
    || type === 'tool_execution_completed'
    || type === 'tool_execution_uncertain'
}

export function buildToolPresentation(
  items: ProcessPresentationItem[],
  options: BuildToolPresentationOptions,
): ToolProcessPresentation {
  const toolCalls: ToolPresentation[] = []
  const callsById = new Map<string, ToolPresentation>()
  const allCallsById = new Map<string, ToolPresentation>()
  const callsByMessageId = new Map<string, ToolPresentation>()
  const callsByAgentId = new Map<string, ToolPresentation>()
  const results: Array<{ key: string; callId: string; content: unknown }> = []
  const collaborationMessages: Array<{ key: string; message: Message }> = []
  const otherItems: ProcessPresentationItem[] = []

  for (const item of items) {
    if (item.kind === 'event') {
      if (!isToolLifecycleEvent(item)) otherItems.push(item)
      continue
    }

    const message = item.message
    if (isCollaborationMessage(message)) {
      collaborationMessages.push({ key: item.key, message })
      continue
    }
    if (Array.isArray(message.tool_calls) && message.tool_calls.length > 0) {
      const assistantText = messageContentText(message).trim() ? messageContentText(message) : ''
      message.tool_calls.forEach((call, index) => {
        const callId = toolCallId(call)
        const toolCall: ToolPresentation = {
          key: `tool:${callId || `${item.key}:${index}`}`,
          name: toolCallName(call),
          assistantText: index === 0 ? assistantText : '',
          arguments: formatToolArguments(call),
          output: '',
          outputState: options.isLive && !options.runFinished ? 'running' : 'missing',
          collaborationMessages: [],
        }
        toolCalls.push(toolCall)
        if (callId && !callsById.has(callId)) {
          callsById.set(callId, toolCall)
          allCallsById.set(callId, toolCall)
        }
        const targetId = toolCallTargetId(call)
        if (targetId && (toolCall.name.startsWith('subagent_') || toolCall.name.startsWith('agent_'))) {
          callsByAgentId.set(targetId, toolCall)
        }
      })
      continue
    }

    if (message.role === 'tool') {
      results.push({
        key: item.key,
        callId: String(message.tool_call_id || ''),
        content: message.content,
      })
      continue
    }

    otherItems.push(item)
  }

  const unpairedResults: ToolResultPresentation[] = []
  for (const result of results) {
    const toolCall = callsById.get(result.callId)
    if (toolCall) {
      const output = outputPresentation(result.content)
      toolCall.output = output.output
      toolCall.outputState = output.outputState
      if (toolCall.name.startsWith('subagent_') || toolCall.name.startsWith('agent_')) {
        const receipt = objectValue(result.content)
        if (typeof receipt?.message_id === 'string') callsByMessageId.set(receipt.message_id, toolCall)
        if (typeof receipt?.target_id === 'string') callsByAgentId.set(receipt.target_id, toolCall)
      }
      callsById.delete(result.callId)
      continue
    }

    const output = outputPresentation(result.content)
    unpairedResults.push({
      key: `tool-output:${result.key}`,
      output: output.output,
      outputState: output.outputState,
    })
  }

  for (const { key, message } of collaborationMessages) {
    const linkedCall = (message.related_tool_call_id && allCallsById.get(message.related_tool_call_id))
      || (message.reply_to || []).slice().reverse().map((id) => callsByMessageId.get(id)).find(Boolean)
      || (message.source_agent_id ? callsByAgentId.get(message.source_agent_id) : undefined)
    if (linkedCall) linkedCall.collaborationMessages.push(message)
    else otherItems.push({ key, kind: 'message', message })
  }

  for (const toolCall of toolCalls) {
    if (toolCall.outputState === 'running') toolCall.output = '执行中…'
    if (toolCall.outputState === 'missing') toolCall.output = '未收到输出'
  }

  return { toolCalls, unpairedResults, otherItems }
}

function sessionEventKey(event: SessionEvent) {
  const seq = Number(event.seq)
  if (Number.isFinite(seq) && seq > 0) return `${event.session_id || ''}:${seq}`
  return stableHash(JSON.stringify(event))
}

export function mergeActiveRunEvents(existing: SessionEvent[], incoming: SessionEvent[]) {
  const merged = new Map<string, SessionEvent>()
  for (const event of existing) merged.set(sessionEventKey(event), event)
  for (const event of incoming) merged.set(sessionEventKey(event), event)
  return [...merged.values()].sort((left, right) => Number(left.seq || 0) - Number(right.seq || 0))
}

export function attachesLiveRunToTurn(
  operation: 'chat' | 'compact' | undefined,
  turnIndex: number,
  turnCount: number,
) {
  return operation !== 'compact' && turnCount > 0 && turnIndex === turnCount - 1
}

export function displayedAssistantText(liveText: string, historicalText: string) {
  return liveText || historicalText
}

export function formatRunFailureMessage(snapshot: FailedRunSnapshot) {
  if (snapshot.recoverable) {
    return snapshot.error
      ? `本轮模型请求暂未完成：${snapshot.error}。现场已保存，可直接发送“继续”恢复。`
      : '本轮模型请求暂未完成。现场已保存，可直接发送“继续”恢复。'
  }
  if (snapshot.operation === 'compact') {
    return snapshot.error
      ? `上下文压缩失败：${snapshot.error}。原会话历史和模型上下文未改变。`
      : '上下文压缩失败。原会话历史和模型上下文未改变。'
  }
  const preserved = '已保留本轮已完成工具记录。'
  return snapshot.error ? `运行失败：${snapshot.error}。${preserved}` : `运行失败。${preserved}`
}
