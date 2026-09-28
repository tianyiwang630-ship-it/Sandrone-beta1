export interface Project {
  id: string
  name: string
  workspace_path: string
  workspace_kind: 'managed' | 'external'
  description?: string | null
  created_at: string
  updated_at: string
  is_pinned: boolean
  is_archived: boolean
  readonly is_knowledge_base: boolean
}

export interface Session {
  id: string
  project_id: string | null
  title: string
  workspace_path: string
  created_at: string
  updated_at: string
  message_count: number
  is_pinned: boolean
  is_archived: boolean
}

export interface Message {
  role: string
  content?: unknown
  tool_calls?: Array<Record<string, unknown>> | null
  tool_call_id?: string | null
  message_id?: string | null
  local_id?: string
  delivery_status?: 'sending' | 'waiting' | 'confirming' | 'received' | 'failed'
  partial?: boolean
  source_agent_id?: string | null
  source?: string | null
  reply_to?: string[]
  result_agent_id?: string | null
  result_run_id?: string | null
  related_tool_call_id?: string | null
  _sender_id?: string | null
  _source?: string | null
  _reply_to?: string[]
}

export interface SubagentInfo {
  agent_id: string
  task_name: string
  status: string
  pending_permission?: PendingPermission | null
}

export interface SessionEvent {
  ts?: string
  seq?: number
  session_id?: string
  type?: string
  entry?: Record<string, unknown>
  event?: Record<string, unknown>
  [key: string]: unknown
}

export interface SessionDetail extends Session {
  messages: Message[]
}

export interface ChatStart {
  request_id: string
  session_id: string
  message_id?: string | null
}

export interface RetrospectiveStart {
  session: Session
  run: ChatStart
}

export interface PendingPermission {
  permission_id: string
  tool: string
  risk_level: string
  reason: string
  summary_label: string
  summary: string
  requested_at: string
  expires_at: string
}

export type PermissionDecision = 'allow_once' | 'deny' | 'retry_with_context'

export interface ChatStatus {
  request_id: string
  session_id: string
  status: 'running' | 'stopping' | 'stop_failed' | 'success' | 'failed' | 'interrupted' | 'recoverable'
  operation?: 'chat' | 'compact'
  started_after_seq?: number
  response?: string | null
  error?: string | null
  tool_calls_count: number
  recovery_stage?: string | null
  can_resume?: boolean
  pending_permission?: PendingPermission | null
  created_at: string
  updated_at: string
}

export interface Settings {
  llm_provider: 'openai' | 'deepseek' | 'minimax' | 'zhipu' | 'kimi' | 'siliconflow' | 'custom'
  llm_base_url: string
  llm_api_key: string
  llm_api_keys: Record<string, string>
  llm_model_name: string
  has_api_key: boolean
  permission_mode: string
  theme: string
}

export interface User {
  id: string
  name: string
  role: 'admin' | 'operator' | 'viewer'
}

export interface CapabilityItem {
  name: string
  kind: 'skill' | 'mcp'
  path: string
  summary?: string | null
}

export interface FileInfo {
  name: string
  path: string
  size: number
  is_dir: boolean
}

export interface FileContent {
  path: string
  name: string
  size: number
  language: string
  content: string | null
  previewable: boolean
  message?: string | null
}
