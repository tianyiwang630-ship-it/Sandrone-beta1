import type { Message, SessionEvent } from './types'

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
