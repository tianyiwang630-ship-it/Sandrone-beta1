import type { Message } from './types'

export interface ChatTurn {
  key: string
  user?: Message
  assistants: Message[]
  steps: Message[]
}

interface CollaborationToolLocation {
  turn: ChatTurn
  toolCallId: string
}

function isCollaborationMessage(message: Message) {
  return message.role === 'user'
    && (message.source === 'agent' || message.source === 'subagent_result' || Boolean(message.source_agent_id))
}

function collaborationToolName(call: Record<string, unknown>) {
  const fn = call.function
  const name = fn && typeof fn === 'object' && 'name' in fn ? String(fn.name || '') : ''
  return name.startsWith('subagent_') || name.startsWith('agent_')
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

export function buildChatTurns(messages: Message[]): ChatTurn[] {
  const turns: ChatTurn[] = []
  const collaborationCallsById = new Map<string, CollaborationToolLocation>()
  const collaborationCallsByMessageId = new Map<string, CollaborationToolLocation>()
  const collaborationCallsByAgentId = new Map<string, CollaborationToolLocation>()
  let current: ChatTurn | null = null

  messages.forEach((message, index) => {
    if (isCollaborationMessage(message)) {
      const repliedCall = [...(message.reply_to || [])]
        .reverse()
        .map((messageId) => collaborationCallsByMessageId.get(messageId))
        .find(Boolean)
      const location = repliedCall || (message.source_agent_id
        ? collaborationCallsByAgentId.get(message.source_agent_id)
        : undefined)
      const step = location
        ? { ...message, related_tool_call_id: location.toolCallId }
        : message
      if (location) {
        location.turn.steps.push(step)
      } else {
        if (!current) {
          current = { key: `turn-${index}`, assistants: [], steps: [] }
          turns.push(current)
        }
        current.steps.push(step)
      }
      return
    }

    if (message.role === 'user') {
      current = { key: `turn-${index}`, user: message, assistants: [], steps: [] }
      turns.push(current)
      return
    }

    if (!current) {
      current = { key: `turn-${index}`, assistants: [], steps: [] }
      turns.push(current)
    }

    if (message.role === 'assistant' && Array.isArray(message.tool_calls) && message.tool_calls.length > 0) {
      current.steps.push(message)
      for (const call of message.tool_calls) {
        if (!collaborationToolName(call)) continue
        const toolCallId = String(call.id || '')
        if (!toolCallId) continue
        const location = { turn: current, toolCallId }
        collaborationCallsById.set(toolCallId, location)
        const targetId = toolCallTargetId(call)
        if (targetId) collaborationCallsByAgentId.set(targetId, location)
      }
      return
    }

    if (message.role === 'tool') {
      current.steps.push(message)
      const location = message.tool_call_id ? collaborationCallsById.get(message.tool_call_id) : undefined
      const receipt = objectValue(message.content)
      const messageId = typeof receipt?.message_id === 'string' ? receipt.message_id : null
      const targetId = typeof receipt?.target_id === 'string' ? receipt.target_id : null
      if (location && messageId) collaborationCallsByMessageId.set(messageId, location)
      if (location && targetId) collaborationCallsByAgentId.set(targetId, location)
      return
    }

    if (message.role === 'assistant') {
      const content = typeof message.content === 'string'
        ? message.content
        : message.content == null ? '' : JSON.stringify(message.content)
      if (content?.trim()) {
        current.assistants.push(message)
      } else {
        current.steps.push(message)
      }
      return
    }

    current.steps.push(message)
  })

  return turns
}
