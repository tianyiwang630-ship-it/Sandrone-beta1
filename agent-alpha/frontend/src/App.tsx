import {
  Code2,
  Copy,
  Eye,
  EyeOff,
  GripVertical,
  KeyRound,
  MessageSquarePlus,
  PanelRightOpen,
  Pencil,
  Play,
  Pin,
  Plus,
  Settings,
  ShieldCheck,
  Square,
  Trash2,
  UserRound,
  Wrench,
} from 'lucide-react'
import {
  DragEvent as ReactDragEvent,
  FormEvent,
  ChangeEvent,
  KeyboardEvent,
  MouseEvent as ReactMouseEvent,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { api } from './api/client'
import {
  ALIGNMENT_PROMPT_PREFIX,
  draftAfterSend,
  insertAlignmentPrompt,
  removeUnchangedAlignmentPrompt,
} from './alignmentPrompt'
import sandroneIcon from './assets/sandrone-icon.png'
import {
  clampScrollTop,
  isCurrentSessionRequest,
  readSessionScrollTop,
  removeSessionScrollTop,
  withoutSession,
  writeSessionScrollTop,
} from './chatScroll'
import {
  attachesLiveRunToTurn,
  displayedAssistantText,
  mergeActiveRunEvents,
  mergeProcessPresentation,
} from './chatPresentation'
import FileDrawer from './components/FileDrawer'
import KnowledgeBaseComposerActions from './components/KnowledgeBaseComposerActions'
import KnowledgeBaseProjectAction from './components/KnowledgeBaseProjectAction'
import {
  acquireComposerUploadLock,
  collectComposerUploadPaths,
  prepareComposerUploadDraftUpdate,
  selectComposerUploadTargetDraft,
  type ComposerUploadKind,
} from './composerUploadPaths'
import { EMPTY_STATE_QUOTES } from './emptyStateQuotes'
import {
  INITIALIZE_KNOWLEDGE_BASE_PROMPT,
  MAINTAIN_KNOWLEDGE_BASE_PROMPT,
  insertKnowledgeBaseAdditionDraft,
  insertKnowledgeBaseRemovalDraft,
  replaceProjectById,
} from './knowledgeBase'
import { renderMarkdown } from './markdown'
import {
  hasPendingPermission,
  isRetryInstructionValid,
  remainingPermissionSeconds,
} from './permissionPrompt'
import {
  emptySessionMessageQueue,
  enqueuePriorityMessage,
  enqueueQueuedMessage,
  moveQueuedMessage,
  pauseMessageQueue,
  resumeMessageQueue,
  takeNextQueuedMessage,
  withdrawQueuedMessage,
  type QueuedMessage,
  type SessionMessageQueue,
} from './messageQueue'
import { excludeDeletedSessions } from './sessionDeletion'
import {
  mergeSessionDetail,
  replaceSessionSummary,
  validateSessionTitle,
} from './sessionRename'
import type {
  CapabilityItem,
  Message,
  PendingPermission,
  PermissionDecision,
  Project,
  Session,
  SessionDetail,
  SessionEvent,
  Settings as SettingsType,
  UploadConflictItem,
  User,
} from './types'
import {
  buildFolderFiles,
  checkProjectUploadConflicts,
  uploadProjectFiles,
  type ConflictStrategy,
  type UploadEntry,
} from './upload'

type CenterView = 'chat' | 'settings' | 'users' | 'capabilities' | 'api'

interface ChatTurn {
  key: string
  user?: Message
  assistant?: Message
  steps: Message[]
}

interface RunningSession {
  requestId: string
  status: 'starting' | 'running' | 'stopping'
  startedAfterSeq: number
  operation?: 'chat' | 'compact'
  pendingPermission?: PendingPermission | null
}

interface FailedRunSnapshot {
  requestId: string
  startedAfterSeq: number
  error: string
  operation?: 'chat' | 'compact'
  recoverable?: boolean
}

interface QueueDropTarget {
  id: string
  placement: 'before' | 'after'
}

interface ComposerUploadBatch {
  projectId: string
  draftKey: string | null
  kind: ComposerUploadKind
  entries: UploadEntry[]
}

const FALLBACK_COMPOSER_SKILLS: CapabilityItem[] = [
  { name: 'ljg-paper', kind: 'skill', path: '', summary: '论文阅读和结构化讲解' },
  { name: 'ljg-plain', kind: 'skill', path: '', summary: '把复杂内容讲成白话' },
  { name: 'pdf', kind: 'skill', path: '', summary: '读取、拆分、合并或生成 PDF' },
]

const SHELL_RESIZER_WIDTH = 8
const MIN_CHAT_WIDTH = 520
const MIN_CHAT_WIDTH_WITH_DRAWER = 180
const MIN_DRAWER_WIDTH = 520

function pickEmptyStateQuote(currentQuotes: Record<string, string>) {
  const usedQuotes = new Set(Object.values(currentQuotes))
  const availableQuotes = EMPTY_STATE_QUOTES.filter((quote) => !usedQuotes.has(quote))
  const pool = availableQuotes.length ? availableQuotes : EMPTY_STATE_QUOTES
  return pool[Math.floor(Math.random() * pool.length)]
}

function messageText(message: Message): string {
  const value = message.content
  if (typeof value === 'string') return value
  if (value == null) return ''
  return JSON.stringify(value, null, 2)
}

function firstLine(value: string, fallback: string) {
  return value
    .split('\n')
    .map((line) => line.trim())
    .find(Boolean)
    ?.slice(0, 140) || fallback
}

function toolCallName(call: Record<string, unknown>) {
  const fn = call.function
  if (fn && typeof fn === 'object' && 'name' in fn) {
    return String((fn as { name?: unknown }).name || 'tool')
  }
  return String(call.name || call.type || 'tool')
}

function hasToolCalls(message: Message) {
  return Array.isArray(message.tool_calls) && message.tool_calls.length > 0
}

function processSummary(message: Message) {
  if (hasToolCalls(message)) {
    const names = message.tool_calls?.map(toolCallName).join(', ')
    return names ? `调用工具 ${names}` : '准备调用工具'
  }
  if (message.role === 'tool') {
    return firstLine(messageText(message), '工具返回结果')
  }
  return firstLine(messageText(message), '正在思考')
}

function buildChatTurns(messages: Message[]): ChatTurn[] {
  const turns: ChatTurn[] = []
  let current: ChatTurn | null = null

  messages.forEach((message, index) => {
    if (message.role === 'user') {
      current = { key: `turn-${index}`, user: message, steps: [] }
      turns.push(current)
      return
    }

    if (!current) {
      current = { key: `turn-${index}`, steps: [] }
      turns.push(current)
    }

    if (message.role === 'tool' || hasToolCalls(message)) {
      current.steps.push(message)
      return
    }

    if (message.role === 'assistant') {
      if (messageText(message).trim()) {
        current.assistant = message
      } else {
        current.steps.push(message)
      }
      return
    }

    current.steps.push(message)
  })

  return turns
}

function collectToolNames(steps: Message[]) {
  const names: string[] = []
  steps.forEach((step) => {
    if (!Array.isArray(step.tool_calls)) return
    step.tool_calls.forEach((call) => names.push(toolCallName(call)))
  })
  return names
}

function summarizeStepList(steps: Message[]) {
  const toolNames = collectToolNames(steps)
  if (!toolNames.length) return `过程 ${steps.length} 条`
  const uniqueNames = [...new Set(toolNames)]
  if (uniqueNames.length === 1) return `调用工具 ${uniqueNames[0]}`
  if (uniqueNames.length === 2) return `调用工具 ${uniqueNames.join('、')}`
  return `调用工具 ${uniqueNames.slice(0, 2).join('、')} 等 ${uniqueNames.length} 个`
}

function liveToolNamesFromEntry(entry: Record<string, unknown>) {
  const calls = entry.tool_calls
  const names = Array.isArray(calls) ? calls.map((call) => toolCallName(call)).filter(Boolean) : []
  return [...new Set(names)]
}

function lastToolNamesBefore(events: SessionEvent[], endIndex: number) {
  for (let index = endIndex; index >= 0; index -= 1) {
    const entry = events[index]?.entry || {}
    if (entry.role === 'assistant') {
      const names = liveToolNamesFromEntry(entry)
      if (names.length) return names
    }
  }
  return []
}

function summarizeLiveStatus(events: SessionEvent[]) {
  const withThinkingPrefix = (status: string) => (status === '正在思考' ? status : `正在思考 · ${status}`)

  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    const payload = eventPayload(event)
    const type = String(event.type || payload.type || '')
    const entry = event.entry || {}

    if (type === 'assistant_delta') return withThinkingPrefix('正在生成回答')
    if (entry.role === 'assistant') {
      const names = liveToolNamesFromEntry(entry)
      if (names.length) return withThinkingPrefix(`调用工具 ${names.join('、')}`)
    }
    if (entry.role === 'tool') {
      const names = lastToolNamesBefore(events, index - 1)
      return withThinkingPrefix(names.length ? `处理 ${names.join('、')} 返回` : '处理工具返回')
    }
    if (type === 'llm_request_started') return '正在思考'
    if (type === 'llm_request_failed') return withThinkingPrefix('模型请求失败')
    if (type === 'llm_retry_scheduled') return withThinkingPrefix('模型请求重试')
    if (type === 'llm_request_exhausted') return withThinkingPrefix('模型请求失败并已停止重试')
    if (type === 'context_compaction_started') return '正在压缩上下文'
    if (type === 'context_compacted') return '上下文已压缩'
    if (type === 'context_compaction_skipped') return '当前上下文无需压缩'
    if (type === 'context_compaction_failed') return '上下文压缩失败'
    if (type === 'context_compaction_interrupted') return '压缩已中断'
    if (type === 'run_failed') return '模型连接失败'
    if (type === 'run_recoverable') return '现场已保存，可继续恢复'
  }
  return '正在思考'
}

function eventPayload(event: SessionEvent) {
  return (event.event || event.entry || event) as Record<string, unknown>
}

function eventSummary(event: SessionEvent) {
  const payload = eventPayload(event)
  const type = String(event.type || payload.type || '运行事件')
  const entry = event.entry || {}
  if (entry.role === 'assistant' && Array.isArray(entry.tool_calls) && entry.tool_calls.length > 0) {
    const names = entry.tool_calls.map((call) => toolCallName(call)).join(', ')
    return names ? `tool ${names}` : 'tool'
  }
  if (entry.role === 'tool') return 'tool result'
  const name = String(payload.tool_name || payload.name || payload.tool || payload.title || '')
  const text = String(payload.message || payload.content || payload.error || '')

  if (type === 'assistant_delta') return 'assistant'
  if (type === 'llm_request_failed') return '模型请求失败'
  if (type === 'llm_retry_scheduled') return '模型请求重试'
  if (type === 'llm_output_truncated') return `模型输出被截断${name ? ` · ${name}` : ''}`
  if (type === 'llm_request_exhausted') return '模型请求失败并已停止重试'
  if (type === 'context_compaction_started') return '开始压缩上下文'
  if (type === 'context_compacted') return '上下文已压缩'
  if (type === 'context_compaction_skipped') return '当前上下文无需压缩'
  if (type === 'context_compaction_failed') return '上下文压缩失败'
  if (type === 'context_compaction_interrupted') return '上下文压缩已中断'
  if (type === 'run_failed') return '模型连接失败'
  if (type === 'run_recoverable') return '模型请求暂未完成，现场已保存'
  if (type.includes('tool') && name) return `工具 ${name}`
  if (name) return `${type} ${name}`
  return firstLine(text, type)
}

function eventDetails(event: SessionEvent) {
  return JSON.stringify(eventPayload(event), null, 2)
}

function isVisibleLiveEvent(event: SessionEvent) {
  const payload = eventPayload(event)
  const type = String(event.type || payload.type || '')
  const entry = event.entry || {}

  if (type === 'assistant_delta') return false
  if (type === 'llm_request_started' || type === 'llm_request_succeeded') return false
  if (entry.role === 'user') return false
  if (entry.role === 'assistant' && !Array.isArray(entry.tool_calls)) return false
  if (entry.role === 'assistant' && Array.isArray(entry.tool_calls) && entry.tool_calls.length > 0) return true
  if (entry.role === 'tool') return true
  return Boolean(type)
}

function assistantDeltaText(events: SessionEvent[]) {
  return events
    .map((event) => {
      const payload = eventPayload(event)
      const type = String(event.type || payload.type || '')
      return type === 'assistant_delta' ? String(payload.content || '') : ''
    })
    .join('')
}

function eventSeq(event: SessionEvent) {
  const seq = Number(event.seq)
  return Number.isFinite(seq) ? seq : 0
}

function latestEventSeq(events: SessionEvent[]) {
  return events.reduce((latest, event) => Math.max(latest, eventSeq(event)), 0)
}

function isDangerNotice(message: string) {
  return /失败|错误|不存在|Error|error/i.test(message)
}

function eventsForRun(events: SessionEvent[], run: { startedAfterSeq: number } | null) {
  if (!run) return []
  return events.filter((event) => eventSeq(event) > run.startedAfterSeq)
}

function failedRunFromEvents(events: SessionEvent[]): FailedRunSnapshot | null {
  const lastEvent = events[events.length - 1]
  if (!lastEvent) return null
  const payload = eventPayload(lastEvent)
  const type = String(lastEvent.type || payload.type || '')
  if (type !== 'run_failed' && type !== 'run_recoverable' && type !== 'context_compaction_failed') return null

  const failedSeq = eventSeq(lastEvent)
  let startedAfterSeq = 0
  const requestId = String(payload.request_id || '')
  for (let index = events.length - 2; index >= 0; index -= 1) {
    const event = events[index]
    if (eventSeq(event) >= failedSeq) continue
    const previousPayload = eventPayload(event)
    const previousType = String(event.type || previousPayload.type || '')
    if (
      type === 'context_compaction_failed' &&
      previousType === 'context_compaction_started' &&
      String(previousPayload.request_id || '') === requestId
    ) {
      startedAfterSeq = eventSeq(event) - 1
      break
    }
    if ((event.entry as Message | undefined)?.role === 'user') {
      startedAfterSeq = eventSeq(event)
      break
    }
  }

  return {
    requestId,
    startedAfterSeq,
    error: String(payload.error_message || payload.error || ''),
    operation: type === 'context_compaction_failed' ? 'compact' : 'chat',
    recoverable: type === 'run_recoverable',
  }
}

function formatRunFailureMessage(snapshot: FailedRunSnapshot) {
  if (snapshot.recoverable) {
    return snapshot.error
      ? `本轮模型请求暂未完成：${snapshot.error}。现场已保存，可直接发送“继续”恢复。`
      : '本轮模型请求暂未完成。现场已保存，可直接发送“继续”恢复。'
  }
  if (snapshot.operation === 'compact') {
    return snapshot.error ? `上下文压缩失败：${snapshot.error}。原会话历史和模型上下文未改变。` : '上下文压缩失败。原会话历史和模型上下文未改变。'
  }
  const preserved = '已保留本轮已完成工具记录。'
  return snapshot.error ? `模型连接失败：${snapshot.error}。${preserved}` : `模型连接失败。${preserved}`
}

function renderProcessContent(step: Message) {
  if (hasToolCalls(step)) {
    const toolNames = step.tool_calls?.map(toolCallName).join(', ')
    return toolNames ? `调用工具: ${toolNames}` : '调用工具'
  }
  return messageText(step)
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatPermissionCountdown(seconds: number) {
  if (seconds <= 0) return '即将超时'
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return minutes ? `${minutes} 分 ${remainder} 秒` : `${remainder} 秒`
}

function permissionRiskLabel(level: string) {
  if (level === 'high') return '高风险'
  if (level === 'low') return '低风险'
  return '中等风险'
}

function shortPath(path: string) {
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
  if (parts.length <= 4) return path
  return `${parts.slice(0, 1).join('/')}/.../${parts.slice(-3).join('/')}`
}

const SELECTED_PROJECT_STORAGE_KEY = 'sandrone:selectedProjectId'
const SELECTED_SESSION_STORAGE_KEY = 'sandrone:selectedSessionId'
const DRAFT_STORAGE_PREFIX = 'sandrone:draft:'
const ALIGNMENT_STORAGE_PREFIX = 'sandrone:alignment:'

function readLocalValue(key: string) {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeLocalValue(key: string, value: string | null) {
  try {
    if (value == null || value === '') window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    // Local storage is a convenience cache; the app should keep working without it.
  }
}

function draftKeyFor(projectId: string | null, sessionId: string | null) {
  if (sessionId) return `${DRAFT_STORAGE_PREFIX}session:${sessionId}`
  if (projectId) return `${DRAFT_STORAGE_PREFIX}project:${projectId}`
  return null
}

function alignmentKeyFor(projectId: string | null, sessionId: string | null) {
  if (sessionId) return `${ALIGNMENT_STORAGE_PREFIX}session:${sessionId}`
  if (projectId) return `${ALIGNMENT_STORAGE_PREFIX}project:${projectId}`
  return null
}

function localStorageOrNull(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function latestUserEventSeq(events: SessionEvent[]) {
  let seq = 0
  for (const event of events) {
    if ((event.entry as Message | undefined)?.role === 'user') {
      seq = Math.max(seq, typeof event.seq === 'number' ? event.seq : 0)
    }
  }
  return seq
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(() => readLocalValue(SELECTED_PROJECT_STORAGE_KEY))
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(() => readLocalValue(SELECTED_SESSION_STORAGE_KEY))
  const [sessionDetail, setSessionDetail] = useState<SessionDetail | null>(null)
  const [draft, setDraft] = useState('')
  const [alignmentEnabled, setAlignmentEnabled] = useState(false)
  const [view, setView] = useState<CenterView>('chat')
  const [settings, setSettings] = useState<SettingsType | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [capabilities, setCapabilities] = useState<CapabilityItem[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [projectMenuOpen, setProjectMenuOpen] = useState(false)
  const [initializingKnowledgeBaseProjectId, setInitializingKnowledgeBaseProjectId] = useState<string | null>(null)
  const [pendingMessagesBySession, setPendingMessagesBySession] = useState<Record<string, Message[]>>({})
  const [messageQueuesBySession, setMessageQueuesBySession] = useState<Record<string, SessionMessageQueue>>({})
  const [liveEventsBySession, setLiveEventsBySession] = useState<Record<string, SessionEvent[]>>({})
  const [runningSessions, setRunningSessions] = useState<Record<string, RunningSession>>({})
  const [failedRunsBySession, setFailedRunsBySession] = useState<Record<string, FailedRunSnapshot>>({})
  const [apiKeyVisible, setApiKeyVisible] = useState(false)
  const [emptyStateQuotesByKey, setEmptyStateQuotesByKey] = useState<Record<string, string>>({})
  const [composerMenuOpen, setComposerMenuOpen] = useState(false)
  const [retrospectiveStarting, setRetrospectiveStarting] = useState(false)
  const [composerUploading, setComposerUploading] = useState(false)
  const [composerConflicts, setComposerConflicts] = useState<UploadConflictItem[]>([])
  const [composerPendingUpload, setComposerPendingUpload] = useState<ComposerUploadBatch | null>(null)
  const [showComposerConflictDialog, setShowComposerConflictDialog] = useState(false)
  const [permissionInstruction, setPermissionInstruction] = useState('')
  const [permissionSubmittingId, setPermissionSubmittingId] = useState<string | null>(null)
  const [permissionError, setPermissionError] = useState<string | null>(null)
  const [permissionNow, setPermissionNow] = useState(() => Date.now())
  const [sessionRename, setSessionRename] = useState<{
    session: Session
    draft: string
    saving: boolean
    error: string | null
  } | null>(null)
  const [queuedMessageToWithdraw, setQueuedMessageToWithdraw] = useState<{
    sessionId: string
    message: QueuedMessage
  } | null>(null)
  const [draggedQueuedMessageId, setDraggedQueuedMessageId] = useState<string | null>(null)
  const [queueDropTarget, setQueueDropTarget] = useState<QueueDropTarget | null>(null)
  const [fileDrawerRefreshKey, setFileDrawerRefreshKey] = useState(0)
  const [sidebarWidth, setSidebarWidth] = useState(306)
  const [drawerWidth, setDrawerWidth] = useState(760)
  const [draggingPane, setDraggingPane] = useState<'sidebar' | 'drawer' | null>(null)
  const messageStreamRef = useRef<HTMLDivElement | null>(null)
  const scrollPositionsRef = useRef<Record<string, number>>({})
  const pendingScrollRestoreRef = useRef<{ sessionId: string; scrollTop: number } | null>(null)
  const previousSelectedSessionIdRef = useRef<string | null>(null)
  const latestSessionsRequestRef = useRef(0)
  const latestDetailRequestBySessionRef = useRef<Record<string, number>>({})
  const scrollPersistTimerRef = useRef<number | null>(null)
  const resumeInFlightRef = useRef(new Set<string>())
  const finalizingRunsRef = useRef(new Set<string>())
  const visibleRefreshFrameRef = useRef<number | null>(null)
  const visibleRefreshInFlightRef = useRef(false)
  const dragStateRef = useRef({ x: 0, sidebarWidth: 306, drawerWidth: 760 })
  const selectedProjectIdRef = useRef<string | null>(null)
  const selectedSessionIdRef = useRef<string | null>(null)
  const messageQueuesRef = useRef<Record<string, SessionMessageQueue>>({})
  const runningSessionsRef = useRef<Record<string, RunningSession>>({})
  const draftRef = useRef('')
  const draftKeyRef = useRef<string | null>(null)
  const alignmentKeyRef = useRef<string | null>(null)
  const alignmentEnabledRef = useRef(false)
  const initializingKnowledgeBaseProjectIdRef = useRef<string | null>(null)
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null)
  const composerUploadBusyRef = useRef(false)
  const deletedSessionIdsRef = useRef(new Set<string>())
  const composerFileInputRef = useRef<HTMLInputElement | null>(null)
  const composerFolderInputRef = useRef<HTMLInputElement | null>(null)
  const composerMenuRef = useRef<HTMLDivElement | null>(null)
  const composerPlusButtonRef = useRef<HTMLButtonElement | null>(null)
  const [apiDraft, setApiDraft] = useState({
    llm_provider: 'openai' as SettingsType['llm_provider'],
    llm_base_url: '',
    llm_api_key: '',
    llm_model_name: '',
  })

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) || null,
    [projects, selectedProjectId],
  )
  const composerSkillItems = useMemo(() => {
    const skills = capabilities
      .filter((item) => item.kind === 'skill')
      .sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'))
    return skills.length ? skills : FALLBACK_COMPOSER_SKILLS
  }, [capabilities])

  const currentPendingMessages = selectedSessionId ? pendingMessagesBySession[selectedSessionId] || [] : []
  const currentMessageQueue = selectedSessionId
    ? messageQueuesBySession[selectedSessionId] || emptySessionMessageQueue()
    : emptySessionMessageQueue()
  const currentQueuedMessages = currentMessageQueue.items
  const currentLiveEvents = selectedSessionId ? liveEventsBySession[selectedSessionId] || [] : []
  const selectedRun = selectedSessionId ? runningSessions[selectedSessionId] || null : null
  const currentPendingPermission = selectedRun?.pendingPermission || null
  const pendingPermissionCount = Object.values(runningSessions).filter(hasPendingPermission).length
  const currentPermissionSeconds = currentPendingPermission
    ? remainingPermissionSeconds(currentPendingPermission.expires_at, permissionNow)
    : 0
  const persistedFailedRun = useMemo(() => failedRunFromEvents(currentLiveEvents), [currentLiveEvents])
  const currentFailedRun = selectedSessionId ? failedRunsBySession[selectedSessionId] || persistedFailedRun : null
  const currentLiveWindow = selectedRun || currentFailedRun
  const isShowingFailedRun = Boolean(currentFailedRun && !selectedRun)
  const isShowingRecoverableRun = Boolean(currentFailedRun?.recoverable && !selectedRun)
  const currentRunEvents = useMemo(
    () => eventsForRun(currentLiveEvents, currentLiveWindow),
    [currentLiveEvents, currentLiveWindow],
  )
  const currentStreamText = useMemo(
    () => assistantDeltaText(currentRunEvents),
    [currentRunEvents],
  )
  const displayMessages = useMemo(
    () => [...(sessionDetail?.messages || []), ...currentPendingMessages],
    [sessionDetail?.messages, currentPendingMessages],
  )
  const chatTurns = useMemo(() => buildChatTurns(displayMessages), [displayMessages])
  const visibleLiveEvents = useMemo(
    () => currentRunEvents.filter(isVisibleLiveEvent),
    [currentRunEvents],
  )
  const liveRunAttachedToChat = Boolean(
    currentLiveWindow && currentLiveWindow.operation !== 'compact' && chatTurns.length > 0,
  )
  const emptyStateKey = selectedSessionId || (selectedProjectId ? `project:${selectedProjectId}` : 'global')
  const currentEmptyStateQuote = emptyStateQuotesByKey[emptyStateKey]
  const showEmptyState = !displayMessages.length && !selectedRun && !currentFailedRun
  const shellGridColumns = drawerOpen
    ? `${sidebarWidth}px ${SHELL_RESIZER_WIDTH}px minmax(${MIN_CHAT_WIDTH_WITH_DRAWER}px, 1fr) ${drawerWidth}px`
    : `${sidebarWidth}px ${SHELL_RESIZER_WIDTH}px minmax(${MIN_CHAT_WIDTH}px, 1fr)`

  useEffect(() => {
    if (!pendingPermissionCount) return
    setPermissionNow(Date.now())
    const timer = window.setInterval(() => setPermissionNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [pendingPermissionCount])

  useEffect(() => {
    setPermissionInstruction('')
    setPermissionError(null)
  }, [currentPendingPermission?.permission_id])

  const loadProjects = async () => {
    const data = await api.listProjects()
    setProjects(data)
    setSelectedProjectId((current) => {
      if (data.some((project) => project.id === current)) return current
      const stored = readLocalValue(SELECTED_PROJECT_STORAGE_KEY)
      if (data.some((project) => project.id === stored)) return stored
      return data[0]?.id || null
    })
  }

  const refreshProjectKnowledgeBaseStatus = async (projectId: string | null) => {
    if (!projectId) return
    try {
      const project = await api.getProject(projectId)
      setProjects((current) => replaceProjectById(current, project))
    } catch {
      // Knowledge-base identity refresh is intentionally silent and keeps the last known state.
    }
  }

  const loadSessions = async (projectId = selectedProjectId, preferredSessionId = selectedSessionIdRef.current) => {
    const requestSequence = latestSessionsRequestRef.current + 1
    latestSessionsRequestRef.current = requestSequence
    if (!projectId) {
      setSessions([])
      setSelectedSessionId(null)
      return
    }
    const data = await api.listProjectSessions(projectId)
    if (selectedProjectIdRef.current !== projectId || latestSessionsRequestRef.current !== requestSequence) return
    const nextSessions = excludeDeletedSessions(data.sessions, deletedSessionIdsRef.current)
    setSessions(nextSessions)
    setSelectedSessionId((current) => {
      if (nextSessions.some((session) => session.id === current)) return current
      if (nextSessions.some((session) => session.id === preferredSessionId)) return preferredSessionId
      const stored = readLocalValue(SELECTED_SESSION_STORAGE_KEY)
      if (nextSessions.some((session) => session.id === stored)) return stored
      return nextSessions[0]?.id || null
    })
  }

  const captureSessionScroll = (sessionId: string | null, persist = false) => {
    const stream = messageStreamRef.current
    if (!sessionId || !stream) return null
    const scrollTop = Math.max(0, stream.scrollTop)
    scrollPositionsRef.current[sessionId] = scrollTop
    if (persist) writeSessionScrollTop(localStorageOrNull(), sessionId, scrollTop)
    return scrollTop
  }

  const persistVisibleSessionScroll = () => {
    captureSessionScroll(selectedSessionIdRef.current, true)
  }

  const handleMessageStreamScroll = () => {
    const sessionId = selectedSessionIdRef.current
    if (!sessionId) return
    captureSessionScroll(sessionId)
    if (scrollPersistTimerRef.current != null) window.clearTimeout(scrollPersistTimerRef.current)
    scrollPersistTimerRef.current = window.setTimeout(() => {
      scrollPersistTimerRef.current = null
      const scrollTop = scrollPositionsRef.current[sessionId]
      if (scrollTop != null) writeSessionScrollTop(localStorageOrNull(), sessionId, scrollTop)
    }, 150)
  }

  const loadSessionDetail = async (
    sessionId = selectedSessionId,
    options: {
      preserveScroll?: boolean
      restoreStoredScroll?: boolean
      removePendingContent?: string
      finishLiveRun?: boolean
    } = {},
  ) => {
    if (!sessionId) {
      setSessionDetail(null)
      return null
    }
    const requestSequence = (latestDetailRequestBySessionRef.current[sessionId] || 0) + 1
    latestDetailRequestBySessionRef.current[sessionId] = requestSequence
    let scrollTop: number | null = null
    if (options.restoreStoredScroll) {
      scrollTop = sessionId in scrollPositionsRef.current
        ? scrollPositionsRef.current[sessionId]
        : readSessionScrollTop(localStorageOrNull(), sessionId)
      scrollPositionsRef.current[sessionId] = scrollTop
    } else if (options.preserveScroll) {
      scrollTop = captureSessionScroll(sessionId)
    }
    if (options.finishLiveRun) finalizingRunsRef.current.add(sessionId)
    let nextDetail: SessionDetail
    try {
      nextDetail = await api.getSession(sessionId)
    } finally {
      if (options.finishLiveRun) finalizingRunsRef.current.delete(sessionId)
    }
    if (deletedSessionIdsRef.current.has(sessionId)) return null
    if (!isCurrentSessionRequest(
      selectedSessionIdRef.current,
      sessionId,
      latestDetailRequestBySessionRef.current[sessionId],
      requestSequence,
    )) {
      return null
    }
    if (scrollTop != null) pendingScrollRestoreRef.current = { sessionId, scrollTop }
    setSessionDetail(nextDetail)
    if (options.removePendingContent !== undefined) {
      setPendingMessagesBySession((current) => {
        const messages = current[sessionId] || []
        let removed = false
        const nextMessages = messages.filter((message) => {
          if (!removed && message.role === 'user' && messageText(message) === options.removePendingContent) {
            removed = true
            return false
          }
          return true
        })
        if (nextMessages.length === messages.length) return current
        const next = { ...current }
        if (nextMessages.length) next[sessionId] = nextMessages
        else delete next[sessionId]
        return next
      })
    }
    if (options.finishLiveRun) {
      const remainingRuns = withoutSession(runningSessionsRef.current, sessionId)
      runningSessionsRef.current = remainingRuns
      setRunningSessions(remainingRuns)
    }
    return nextDetail
  }

  const refreshSupportData = async () => {
    const [nextSettings, nextUsers, capabilityData] = await Promise.all([
      api.getSettings(),
      api.listUsers(),
      api.listCapabilities(),
    ])
    setSettings(nextSettings)
    setApiDraft({
      llm_provider: nextSettings.llm_provider,
      llm_base_url: nextSettings.llm_base_url,
      llm_api_key: nextSettings.llm_api_key,
      llm_model_name: nextSettings.llm_model_name,
    })
    setUsers(nextUsers)
    setCapabilities(capabilityData.items)
  }

  useEffect(() => {
    void loadProjects()
    void refreshSupportData()
  }, [])

  useEffect(() => {
    selectedProjectIdRef.current = selectedProjectId
    writeLocalValue(SELECTED_PROJECT_STORAGE_KEY, selectedProjectId)
    setSessionDetail(null)
    void loadSessions(selectedProjectId)
  }, [selectedProjectId])

  useEffect(() => {
    const previousSessionId = previousSelectedSessionIdRef.current
    if (previousSessionId && previousSessionId !== selectedSessionId) {
      captureSessionScroll(previousSessionId, true)
    }
    previousSelectedSessionIdRef.current = selectedSessionId
    selectedSessionIdRef.current = selectedSessionId
    setFailedRunsBySession({})
    void loadSessionDetail(selectedSessionId, { restoreStoredScroll: true })
  }, [selectedSessionId])

  useEffect(() => {
    writeLocalValue(SELECTED_SESSION_STORAGE_KEY, selectedSessionId)
  }, [selectedSessionId])

  useEffect(() => {
    const nextDraftKey = draftKeyFor(selectedProjectId, selectedSessionId)
    const nextAlignmentKey = alignmentKeyFor(selectedProjectId, selectedSessionId)
    draftKeyRef.current = nextDraftKey
    alignmentKeyRef.current = nextAlignmentKey
    const nextDraft = nextDraftKey ? readLocalValue(nextDraftKey) || '' : ''
    draftRef.current = nextDraft
    setDraft(nextDraft)
    const nextAlignmentEnabled = nextAlignmentKey ? readLocalValue(nextAlignmentKey) === '1' : false
    alignmentEnabledRef.current = nextAlignmentEnabled
    setAlignmentEnabled(nextAlignmentEnabled)
  }, [selectedProjectId, selectedSessionId])

  useEffect(() => {
    messageQueuesRef.current = messageQueuesBySession
  }, [messageQueuesBySession])

  useEffect(() => {
    runningSessionsRef.current = runningSessions
  }, [runningSessions])

  useEffect(() => {
    if (!composerMenuOpen) return

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (composerMenuRef.current?.contains(target)) return
      if (composerPlusButtonRef.current?.contains(target)) return
      setComposerMenuOpen(false)
    }

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setComposerMenuOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [composerMenuOpen])

  useEffect(() => {
    if (!notice || isDangerNotice(notice)) return
    const timer = window.setTimeout(() => {
      setNotice((current) => (current === notice ? null : current))
    }, 3000)
    return () => window.clearTimeout(timer)
  }, [notice])

  useEffect(() => {
    if (selectedRun || currentFailedRun || displayMessages.length || currentEmptyStateQuote) return
    setEmptyStateQuotesByKey((current) => ({
      ...current,
      [emptyStateKey]: pickEmptyStateQuote(current),
    }))
  }, [currentEmptyStateQuote, currentFailedRun, displayMessages.length, emptyStateKey, selectedRun])

  useLayoutEffect(() => {
    const pending = pendingScrollRestoreRef.current
    const stream = messageStreamRef.current
    if (!pending || !stream || sessionDetail?.id !== pending.sessionId || selectedSessionId !== pending.sessionId) return
    const scrollTop = clampScrollTop(pending.scrollTop, stream.scrollHeight, stream.clientHeight)
    stream.scrollTop = scrollTop
    scrollPositionsRef.current[pending.sessionId] = scrollTop
    pendingScrollRestoreRef.current = null
  }, [selectedSessionId, sessionDetail])

  useEffect(() => {
    if (!draggingPane) return

    const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

    const handleMouseMove = (event: globalThis.MouseEvent) => {
      const deltaX = event.clientX - dragStateRef.current.x
      if (draggingPane === 'sidebar') {
        const minChatWidth = drawerOpen ? MIN_CHAT_WIDTH_WITH_DRAWER : MIN_CHAT_WIDTH
        const maxWidth = Math.max(320, window.innerWidth - (drawerOpen ? drawerWidth : 0) - minChatWidth - SHELL_RESIZER_WIDTH)
        setSidebarWidth(clamp(dragStateRef.current.sidebarWidth + deltaX, 240, maxWidth))
        return
      }

      const maxWidth = Math.max(MIN_DRAWER_WIDTH, window.innerWidth - sidebarWidth - MIN_CHAT_WIDTH_WITH_DRAWER - SHELL_RESIZER_WIDTH)
      setDrawerWidth(clamp(dragStateRef.current.drawerWidth - deltaX, MIN_DRAWER_WIDTH, maxWidth))
    }

    const handleMouseUp = () => setDraggingPane(null)

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [draggingPane, drawerOpen, drawerWidth, sidebarWidth])

  const startSidebarResize = (event: ReactMouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    dragStateRef.current = { x: event.clientX, sidebarWidth, drawerWidth }
    setDraggingPane('sidebar')
  }

  const startDrawerResize = (event: ReactMouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    dragStateRef.current = { x: event.clientX, sidebarWidth, drawerWidth }
    setDraggingPane('drawer')
  }

  const createProject = async (kind: 'managed' | 'external') => {
    setProjectMenuOpen(false)
    try {
      let project
      if (kind === 'managed') {
        const name = window.prompt('项目名称', '新项目')
        if (!name?.trim()) return
        project = await api.createProject({ name: name.trim() })
      } else {
        const picked = await api.pickProjectFolder()
        if (!picked.path) return
        project = await api.createProject({ workspace_path: picked.path })
      }
      await loadProjects()
      setSelectedProjectId(project.id)
      setView('chat')
      setNotice(null)
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    }
  }

  const createSessionForProject = async (projectId: string, title?: string) => {
    const session = await api.createSession(projectId, title)
    const projectDraftKey = draftKeyFor(projectId, null)
    const sessionDraftKey = draftKeyFor(projectId, session.id)
    const projectAlignmentKey = alignmentKeyFor(projectId, null)
    const sessionAlignmentKey = alignmentKeyFor(projectId, session.id)
    const projectDraft = projectDraftKey ? readLocalValue(projectDraftKey) : null
    if (projectDraft && projectDraftKey && sessionDraftKey && !readLocalValue(sessionDraftKey)) {
      writeLocalValue(sessionDraftKey, projectDraft)
      writeLocalValue(projectDraftKey, null)
    }
    if (projectAlignmentKey && sessionAlignmentKey && readLocalValue(projectAlignmentKey) === '1') {
      writeLocalValue(sessionAlignmentKey, '1')
      writeLocalValue(projectAlignmentKey, null)
    }
    await loadSessions(projectId)
    selectedSessionIdRef.current = session.id
    setSelectedSessionId(session.id)
    setView('chat')
    return session
  }

  const createSession = async () => {
    if (!selectedProjectId) {
      setNotice('请先新建或选择项目。')
      return
    }
    await createSessionForProject(selectedProjectId)
  }

  const deleteProject = async (project: Project) => {
    const ok = window.confirm(`删除项目「${project.name}」？\n\n只会删除项目记录和它的会话记录，不会删除工作区文件。`)
    if (!ok) return
    await api.deleteProject(project.id)
    if (selectedProjectId === project.id) {
      setSelectedProjectId(null)
      setSelectedSessionId(null)
      setSessionDetail(null)
    }
    await loadProjects()
    setView('chat')
  }

  const deleteSession = async (session: Session) => {
    const ok = window.confirm(`删除会话「${session.title}」？\n\n会删除这场对话的 session 快照、events 和日志，不会删除工作区文件。`)
    if (!ok) return
    const projectId = session.project_id || selectedProjectId
    await api.deleteSession(session.id)
    deletedSessionIdsRef.current.add(session.id)
    if (scrollPersistTimerRef.current != null) {
      window.clearTimeout(scrollPersistTimerRef.current)
      scrollPersistTimerRef.current = null
    }
    scrollPositionsRef.current = withoutSession(scrollPositionsRef.current, session.id)
    latestDetailRequestBySessionRef.current = withoutSession(latestDetailRequestBySessionRef.current, session.id)
    removeSessionScrollTop(localStorageOrNull(), session.id)
    if (projectId && selectedProjectIdRef.current === projectId) {
      const nextSelectedSessionId = excludeDeletedSessions(sessions, deletedSessionIdsRef.current)[0]?.id || null
      setSessions((current) => excludeDeletedSessions(current, deletedSessionIdsRef.current))
      if (selectedSessionIdRef.current === session.id) {
        selectedSessionIdRef.current = nextSelectedSessionId
        setSelectedSessionId(nextSelectedSessionId)
        setSessionDetail(null)
      }
    }
    setLiveEventsBySession((current) => {
      const next = { ...current }
      delete next[session.id]
      return next
    })
    setPendingMessagesBySession((current) => {
      const next = { ...current }
      delete next[session.id]
      return next
    })
    const nextQueues = { ...messageQueuesRef.current }
    delete nextQueues[session.id]
    messageQueuesRef.current = nextQueues
    setMessageQueuesBySession(nextQueues)
    setEmptyStateQuotesByKey((current) => {
      const next = { ...current }
      delete next[session.id]
      return next
    })
    setRunningSessions((current) => {
      const next = { ...current }
      delete next[session.id]
      return next
    })
    setView('chat')
  }

  const renameProject = async (project: Project) => {
    const name = window.prompt('项目新名称', project.name)
    if (name == null) return
    const nextName = name.trim()
    if (!nextName || nextName === project.name) return
    await api.updateProject(project.id, { name: nextName })
    await loadProjects()
    setNotice(`已重命名项目「${nextName}」`)
  }

  const toggleProjectPinned = async (project: Project) => {
    await api.updateProject(project.id, { is_pinned: !project.is_pinned })
    await loadProjects()
  }

  const openRenameSession = (session: Session) => {
    setSessionRename({ session, draft: session.title, saving: false, error: null })
  }

  const submitRenameSession = async (event: FormEvent) => {
    event.preventDefault()
    if (!sessionRename || sessionRename.saving) return
    const trimmed = sessionRename.draft.trim()
    if (!trimmed) {
      setSessionRename((current) => current ? { ...current, error: '会话名称不能为空。' } : current)
      return
    }
    if (trimmed.length > 160) {
      setSessionRename((current) => current ? { ...current, error: '会话名称不能超过 160 个字符。' } : current)
      return
    }
    const nextTitle = validateSessionTitle(sessionRename.draft, sessionRename.session.title)
    if (!nextTitle) {
      setSessionRename(null)
      return
    }

    setSessionRename((current) => current ? { ...current, saving: true, error: null } : current)
    try {
      const updated = await api.updateSession(sessionRename.session.id, { title: nextTitle })
      latestSessionsRequestRef.current += 1
      latestDetailRequestBySessionRef.current[updated.id] =
        (latestDetailRequestBySessionRef.current[updated.id] || 0) + 1
      setSessions((current) => replaceSessionSummary(current, updated))
      setSessionDetail((current) => mergeSessionDetail(current, updated))
      setSessionRename(null)
      setNotice(`已重命名会话「${updated.title}」`)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setSessionRename((current) => current ? {
        ...current,
        saving: false,
        error: message === 'Not Found' ? '会话不存在，请刷新后重试。' : `重命名失败：${message}`,
      } : current)
    }
  }

  const toggleSessionPinned = async (session: Session) => {
    await api.updateSession(session.id, { is_pinned: !session.is_pinned })
    await loadSessions(selectedProjectId)
    if (selectedSessionId === session.id) {
      await loadSessionDetail(session.id, { preserveScroll: true })
    }
  }

  const clearFailedRun = (sessionId: string) => {
    setFailedRunsBySession((current) => {
      if (!current[sessionId]) return current
      const next = { ...current }
      delete next[sessionId]
      return next
    })
  }

  const updatePendingPermission = (sessionId: string, pendingPermission: PendingPermission | null) => {
    const currentRun = runningSessionsRef.current[sessionId]
    if (!currentRun) return
    const nextRuns = {
      ...runningSessionsRef.current,
      [sessionId]: { ...currentRun, pendingPermission },
    }
    runningSessionsRef.current = nextRuns
    setRunningSessions(nextRuns)
  }

  const submitPermissionDecision = async (decision: PermissionDecision) => {
    if (!selectedSessionId || !currentPendingPermission || permissionSubmittingId) return
    const instruction = permissionInstruction.trim()
    if (decision === 'retry_with_context' && !isRetryInstructionValid(instruction)) {
      setPermissionError('请输入追加说明。')
      return
    }
    const permissionId = currentPendingPermission.permission_id
    const sessionId = selectedSessionId
    setPermissionSubmittingId(permissionId)
    setPermissionError(null)
    try {
      await api.resolvePermission(permissionId, decision, decision === 'retry_with_context' ? instruction : undefined)
      updatePendingPermission(sessionId, null)
      setPermissionInstruction('')
    } catch (err) {
      setPermissionError(err instanceof Error ? err.message : String(err))
    } finally {
      setPermissionSubmittingId(null)
    }
  }

  const refreshLiveEvents = async (
    sessionId: string,
    options: { preserveActiveRunEvents?: boolean } = {},
  ) => {
    const preserveActiveRunEvents = options.preserveActiveRunEvents
      ?? Boolean(runningSessionsRef.current[sessionId])
    try {
      const data = await api.getSessionEvents(sessionId)
      setLiveEventsBySession((current) => ({
        ...current,
        [sessionId]: preserveActiveRunEvents
          ? mergeActiveRunEvents(current[sessionId] || [], data.events)
          : data.events,
      }))
      return data.events
    } catch {
      if (!preserveActiveRunEvents) {
        setLiveEventsBySession((current) => ({ ...current, [sessionId]: [] }))
      }
      return []
    }
  }

  useEffect(() => {
    if (!selectedSessionId) return
    void refreshLiveEvents(selectedSessionId)
  }, [selectedSessionId])

  const resumeActiveRun = async (sessionId: string, projectIdForList = selectedProjectIdRef.current) => {
    if (resumeInFlightRef.current.has(sessionId)) return
    resumeInFlightRef.current.add(sessionId)
    let activeRun
    try {
      activeRun = await api.getSessionActiveRun(sessionId)
    } catch {
      resumeInFlightRef.current.delete(sessionId)
      return
    }
    const existingRun = runningSessionsRef.current[sessionId]
    if (existingRun?.requestId === activeRun.request_id) {
      resumeInFlightRef.current.delete(sessionId)
      return
    }

    clearFailedRun(sessionId)
    const events = await refreshLiveEvents(sessionId)
    const startedAfterSeq = activeRun.started_after_seq ?? latestUserEventSeq(events)
    const resumedRuns = {
      ...runningSessionsRef.current,
      [sessionId]: {
        requestId: activeRun.request_id,
        status: 'running',
        startedAfterSeq,
        operation: activeRun.operation || 'chat',
        pendingPermission: activeRun.pending_permission || null,
      },
    } as Record<string, RunningSession>
    runningSessionsRef.current = resumedRuns
    setRunningSessions(resumedRuns)

    try {
      while (true) {
        const status = await api.getChatStatus(activeRun.request_id)
        updatePendingPermission(sessionId, status.pending_permission || null)
        if (status.status === 'running') {
          await refreshLiveEvents(sessionId, { preserveActiveRunEvents: true })
          await new Promise((resolve) => window.setTimeout(resolve, 1000))
          continue
        }
        if (status.status === 'failed') {
          await refreshLiveEvents(sessionId, { preserveActiveRunEvents: true })
          throw new Error(status.error || '运行失败')
        }
        if (status.status === 'recoverable') {
          await refreshLiveEvents(sessionId, { preserveActiveRunEvents: true })
          setFailedRunsBySession((current) => ({
            ...current,
            [sessionId]: {
              requestId: status.request_id,
              startedAfterSeq,
              error: status.error || '',
              operation: status.operation || 'chat',
              recoverable: true,
            },
          }))
        }
        break
      }
      if (selectedSessionIdRef.current === sessionId) {
        await loadSessionDetail(sessionId, { preserveScroll: true, finishLiveRun: true })
      }
      await loadSessions(projectIdForList)
      await refreshLiveEvents(sessionId)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      const requestId = String(activeRun?.request_id || '')
      if (requestId) {
        await refreshLiveEvents(sessionId)
        if (selectedSessionIdRef.current === sessionId) {
          await loadSessionDetail(sessionId, { preserveScroll: true })
        }
        await loadSessions(projectIdForList)
        setFailedRunsBySession((current) => ({
          ...current,
          [sessionId]: { requestId, startedAfterSeq, error: message },
        }))
      }
      setNotice(message === 'Not Found' ? '会话或接口不存在，请刷新后重新选择会话。' : message)
    } finally {
      resumeInFlightRef.current.delete(sessionId)
      await refreshProjectKnowledgeBaseStatus(projectIdForList)
      const remainingRuns = withoutSession(runningSessionsRef.current, sessionId)
      runningSessionsRef.current = remainingRuns
      setRunningSessions(remainingRuns)
      const queuedMessage = popQueuedSessionMessage(sessionId)
      if (queuedMessage) {
        window.setTimeout(() => void runSessionMessage(sessionId, queuedMessage.content, projectIdForList), 0)
      }
    }
  }

  useEffect(() => {
    if (!selectedSessionId) return
    void resumeActiveRun(selectedSessionId)
  }, [selectedSessionId])

  useEffect(() => {
    const refreshVisibleSession = async () => {
      if (visibleRefreshInFlightRef.current || !selectedSessionIdRef.current) return
      visibleRefreshInFlightRef.current = true
      const sessionId = selectedSessionIdRef.current
      void resumeActiveRun(sessionId)
      try {
        const refreshes: Promise<unknown>[] = [refreshLiveEvents(sessionId)]
        if (!finalizingRunsRef.current.has(sessionId)) {
          refreshes.push(loadSessionDetail(sessionId, { preserveScroll: true }))
        }
        await Promise.allSettled(refreshes)
      } finally {
        visibleRefreshInFlightRef.current = false
      }
    }
    const scheduleVisibleRefresh = () => {
      if (document.visibilityState === 'hidden') {
        persistVisibleSessionScroll()
        return
      }
      if (!selectedSessionIdRef.current || visibleRefreshFrameRef.current != null) return
      visibleRefreshFrameRef.current = window.requestAnimationFrame(() => {
        visibleRefreshFrameRef.current = null
        void refreshVisibleSession()
      })
    }
    window.addEventListener('focus', scheduleVisibleRefresh)
    window.addEventListener('beforeunload', persistVisibleSessionScroll)
    document.addEventListener('visibilitychange', scheduleVisibleRefresh)
    return () => {
      window.removeEventListener('focus', scheduleVisibleRefresh)
      window.removeEventListener('beforeunload', persistVisibleSessionScroll)
      document.removeEventListener('visibilitychange', scheduleVisibleRefresh)
      if (visibleRefreshFrameRef.current != null) window.cancelAnimationFrame(visibleRefreshFrameRef.current)
      if (scrollPersistTimerRef.current != null) window.clearTimeout(scrollPersistTimerRef.current)
      persistVisibleSessionScroll()
    }
  }, [])

  const appendPendingUserMessage = (sessionId: string, content: string) => {
    setPendingMessagesBySession((current) => ({
      ...current,
      [sessionId]: [...(current[sessionId] || []), { role: 'user', content }],
    }))
  }

  const ensurePendingUserMessage = (sessionId: string, content: string) => {
    setPendingMessagesBySession((current) => {
      const messages = current[sessionId] || []
      if (messages.some((message) => message.role === 'user' && messageText(message) === content)) {
        return current
      }
      return {
        ...current,
        [sessionId]: [...messages, { role: 'user', content }],
      }
    })
  }

  const removePendingUserMessage = (sessionId: string, content: string) => {
    setPendingMessagesBySession((current) => {
      const messages = current[sessionId] || []
      let removed = false
      const nextMessages = messages.filter((message) => {
        if (!removed && message.role === 'user' && messageText(message) === content) {
          removed = true
          return false
        }
        return true
      })
      const next = { ...current }
      if (nextMessages.length) next[sessionId] = nextMessages
      else delete next[sessionId]
      return next
    })
  }

  const updateSessionMessageQueue = (
    sessionId: string,
    updater: (queue: SessionMessageQueue) => SessionMessageQueue,
  ) => {
    const currentQueue = messageQueuesRef.current[sessionId] || emptySessionMessageQueue()
    const updatedQueue = updater(currentQueue)
    const next = { ...messageQueuesRef.current }
    if (updatedQueue.items.length) next[sessionId] = updatedQueue
    else delete next[sessionId]
    messageQueuesRef.current = next
    setMessageQueuesBySession(next)
    return updatedQueue
  }

  const enqueueSessionMessage = (sessionId: string, content: string, priority = false) => {
    const message = { id: window.crypto.randomUUID(), content }
    updateSessionMessageQueue(
      sessionId,
      (queue) => priority ? enqueuePriorityMessage(queue, message) : enqueueQueuedMessage(queue, message),
    )
  }

  const popQueuedSessionMessage = (sessionId: string) => {
    const currentQueue = messageQueuesRef.current[sessionId] || emptySessionMessageQueue()
    const result = takeNextQueuedMessage(currentQueue)
    const next = { ...messageQueuesRef.current }
    if (result.queue.items.length) next[sessionId] = result.queue
    else delete next[sessionId]
    messageQueuesRef.current = next
    setMessageQueuesBySession(next)
    return result.message
  }

  const updateDraft = (value: string) => {
    draftRef.current = value
    setDraft(value)
    if (draftKeyRef.current) {
      writeLocalValue(draftKeyRef.current, value)
    }
  }

  const focusComposer = (selectionStart: number, selectionEnd = selectionStart) => {
    window.requestAnimationFrame(() => {
      const textarea = composerTextareaRef.current
      if (!textarea) return
      textarea.focus()
      textarea.setSelectionRange(selectionStart, selectionEnd)
    })
  }

  const toggleAlignment = () => {
    const textarea = composerTextareaRef.current
    const currentDraft = textarea?.value ?? draft
    const selectionStart = textarea?.selectionStart ?? draft.length
    const selectionEnd = textarea?.selectionEnd ?? selectionStart
    const nextEnabled = !alignmentEnabledRef.current
    const change = nextEnabled
      ? insertAlignmentPrompt(currentDraft)
      : removeUnchangedAlignmentPrompt(currentDraft, selectionStart, selectionEnd)

    alignmentEnabledRef.current = nextEnabled
    setAlignmentEnabled(nextEnabled)
    if (alignmentKeyRef.current) {
      writeLocalValue(alignmentKeyRef.current, nextEnabled ? '1' : null)
    }
    updateDraft(change.value)
    focusComposer(change.selectionStart, change.selectionEnd)
  }

  const runSessionMessage = async (
    sessionId: string,
    content: string,
    projectIdForList: string | null,
    onSubmitted?: () => void,
  ) => {
    clearFailedRun(sessionId)
    ensurePendingUserMessage(sessionId, content)
    let startedAfterSeq = latestEventSeq(liveEventsBySession[sessionId] || [])
    let requestId = ''
    let submissionNotified = false
    const notifySubmitted = () => {
      if (submissionNotified) return
      submissionNotified = true
      onSubmitted?.()
    }
    try {
      const data = await api.getSessionEvents(sessionId)
      startedAfterSeq = latestEventSeq(data.events)
      setLiveEventsBySession((current) => ({ ...current, [sessionId]: data.events }))
    } catch {
      // Events are an optional live enhancement; chat should still start if this snapshot is unavailable.
    }
    setLiveEventsBySession((current) => ({ ...current, [sessionId]: [] }))
    const startingRuns = {
      ...runningSessionsRef.current,
      [sessionId]: { requestId: '', status: 'starting', startedAfterSeq, operation: 'chat' } as RunningSession,
    }
    runningSessionsRef.current = startingRuns
    setRunningSessions(startingRuns)
    setNotice(null)
    try {
      const run = await api.sendMessage(sessionId, content)
      requestId = run.request_id
      notifySubmitted()
      if (selectedSessionIdRef.current === sessionId) {
        await loadSessionDetail(sessionId, { preserveScroll: true, removePendingContent: content })
      }
      removePendingUserMessage(sessionId, content)
      const runStatus = runningSessionsRef.current[sessionId]?.status === 'stopping' ? 'stopping' : 'running'
      const activeRuns = {
        ...runningSessionsRef.current,
        [sessionId]: { requestId: run.request_id, status: runStatus, startedAfterSeq, operation: 'chat' } as RunningSession,
      }
      runningSessionsRef.current = activeRuns
      setRunningSessions(activeRuns)
      while (true) {
        const status = await api.getChatStatus(run.request_id)
        updatePendingPermission(sessionId, status.pending_permission || null)
        if (status.status === 'running') {
          await refreshLiveEvents(sessionId, { preserveActiveRunEvents: true })
          await new Promise((resolve) => window.setTimeout(resolve, 1000))
          continue
        }
        if (status.status === 'failed') {
          await refreshLiveEvents(sessionId, { preserveActiveRunEvents: true })
          throw new Error(status.error || '运行失败')
        }
        if (status.status === 'recoverable') {
          await refreshLiveEvents(sessionId, { preserveActiveRunEvents: true })
          setFailedRunsBySession((current) => ({
            ...current,
            [sessionId]: {
              requestId: status.request_id,
              startedAfterSeq,
              error: status.error || '',
              operation: status.operation || 'chat',
              recoverable: true,
            },
          }))
        }
        break
      }
      if (selectedSessionIdRef.current === sessionId) {
        await loadSessionDetail(sessionId, {
          preserveScroll: true,
          removePendingContent: content,
          finishLiveRun: true,
        })
      }
      await loadSessions(projectIdForList)
      await refreshLiveEvents(sessionId)
      removePendingUserMessage(sessionId, content)
      setNotice(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      if (requestId) {
        await refreshLiveEvents(sessionId)
        if (selectedSessionIdRef.current === sessionId) {
          await loadSessionDetail(sessionId, { preserveScroll: true })
        }
        await loadSessions(projectIdForList)
        removePendingUserMessage(sessionId, content)
        setFailedRunsBySession((current) => ({
          ...current,
          [sessionId]: { requestId, startedAfterSeq, error: message },
        }))
      }
      setNotice(message === 'Not Found' ? '会话或接口不存在，请刷新后重新选择会话。' : message)
    } finally {
      notifySubmitted()
      await refreshProjectKnowledgeBaseStatus(projectIdForList)
      const remainingRuns = { ...runningSessionsRef.current }
      delete remainingRuns[sessionId]
      runningSessionsRef.current = remainingRuns
      setRunningSessions(remainingRuns)
      const queuedMessage = popQueuedSessionMessage(sessionId)
      if (queuedMessage) {
        window.setTimeout(() => void runSessionMessage(sessionId, queuedMessage.content, projectIdForList), 0)
      }
    }
  }

  const initializeKnowledgeBase = async (project: Project) => {
    if (initializingKnowledgeBaseProjectIdRef.current) return
    initializingKnowledgeBaseProjectIdRef.current = project.id
    setInitializingKnowledgeBaseProjectId(project.id)
    setNotice(null)
    try {
      selectedProjectIdRef.current = project.id
      setSelectedProjectId(project.id)
      const session = await createSessionForProject(project.id, '初始化知识库')
      void runSessionMessage(session.id, INITIALIZE_KNOWLEDGE_BASE_PROMPT, project.id, () => {
        if (initializingKnowledgeBaseProjectIdRef.current === project.id) {
          initializingKnowledgeBaseProjectIdRef.current = null
        }
        setInitializingKnowledgeBaseProjectId((current) => current === project.id ? null : current)
      })
    } catch (err) {
      initializingKnowledgeBaseProjectIdRef.current = null
      setInitializingKnowledgeBaseProjectId(null)
      setNotice(err instanceof Error ? err.message : String(err))
    }
  }

  const sendKnowledgeBasePrompt = async (content: string) => {
    if (!selectedProjectId) return
    let sessionId = selectedSessionId
    if (!sessionId) {
      try {
        const session = await createSessionForProject(selectedProjectId)
        sessionId = session.id
      } catch (err) {
        setNotice(err instanceof Error ? err.message : String(err))
        return
      }
    }

    const activeRun = runningSessionsRef.current[sessionId]
    if (activeRun) {
      enqueueSessionMessage(sessionId, content, activeRun.status === 'stopping')
      setNotice(null)
      return
    }

    const pausedQueue = messageQueuesRef.current[sessionId]
    if (pausedQueue?.paused) {
      updateSessionMessageQueue(sessionId, resumeMessageQueue)
    }
    await runSessionMessage(sessionId, content, selectedProjectId)
  }

  const insertKnowledgeBaseRemoval = () => {
    const textarea = composerTextareaRef.current
    const currentDraft = textarea?.value ?? draft
    const change = insertKnowledgeBaseRemovalDraft(
      currentDraft,
      textarea?.selectionStart,
      textarea?.selectionEnd,
    )
    updateDraft(change.value)
    focusComposer(change.selectionStart, change.selectionEnd)
  }

  const insertKnowledgeBaseAddition = () => {
    const textarea = composerTextareaRef.current
    const currentDraft = textarea?.value ?? draft
    const change = insertKnowledgeBaseAdditionDraft(
      currentDraft,
      textarea?.selectionStart,
      textarea?.selectionEnd,
    )
    updateDraft(change.value)
    focusComposer(change.selectionStart, change.selectionEnd)
  }

  const uploadComposerBatch = async (batch: ComposerUploadBatch, strategy?: ConflictStrategy) => {
    if (!batch.entries.length) return
    const releaseUploadLock = acquireComposerUploadLock(composerUploadBusyRef)
    if (!releaseUploadLock) return
    setComposerUploading(true)
    setNotice(null)
    try {
      const uploadedFiles = await uploadProjectFiles(batch.projectId, '', batch.entries, strategy)
      const paths = collectComposerUploadPaths(batch.kind, batch.entries, uploadedFiles)
      const currentDraftKey = draftKeyRef.current
      const appliesToCurrent = batch.draftKey === currentDraftKey
      const textarea = appliesToCurrent ? composerTextareaRef.current : null
      const storedDraft = batch.draftKey ? readLocalValue(batch.draftKey) || '' : ''
      const targetDraft = selectComposerUploadTargetDraft(
        appliesToCurrent,
        textarea?.value,
        draftRef.current,
        storedDraft,
      )
      const update = prepareComposerUploadDraftUpdate({
        uploadDraftKey: batch.draftKey,
        currentDraftKey,
        currentDraft: targetDraft,
        storedDraft,
        paths,
        selectionStart: textarea?.selectionStart,
        selectionEnd: textarea?.selectionEnd,
        alignmentPromptPrefix: ALIGNMENT_PROMPT_PREFIX,
      })
      if (update.applyToCurrent) {
        updateDraft(update.change.value)
        focusComposer(update.change.selectionStart, update.change.selectionEnd)
      } else if (update.draftKey) {
        writeLocalValue(update.draftKey, update.change.value)
      }
      setShowComposerConflictDialog(false)
      setComposerPendingUpload(null)
      setComposerConflicts([])
      setComposerMenuOpen(false)
      setFileDrawerRefreshKey((value) => value + 1)
      setNotice(`已上传 ${batch.entries.length} 个文件到项目根目录。`)
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    } finally {
      setComposerUploading(false)
      releaseUploadLock()
    }
  }

  const handleComposerPickedFiles = async (kind: ComposerUploadKind, entries: UploadEntry[]) => {
    if (!selectedProject) {
      setNotice('请先选择项目。')
      return
    }
    if (!entries.length) return
    const batch: ComposerUploadBatch = {
      projectId: selectedProject.id,
      draftKey: draftKeyRef.current,
      kind,
      entries,
    }
    const releaseUploadLock = acquireComposerUploadLock(composerUploadBusyRef)
    if (!releaseUploadLock) return
    setComposerUploading(true)
    let readyToUpload = false
    try {
      const conflictData = await checkProjectUploadConflicts(batch.projectId, '', batch.entries)
      if (conflictData.has_conflicts) {
        if (selectedProjectIdRef.current !== batch.projectId) {
          setNotice('项目已切换，请回到原项目重新上传。')
          return
        }
        setComposerPendingUpload(batch)
        setComposerConflicts(conflictData.conflicts)
        setShowComposerConflictDialog(true)
        setComposerMenuOpen(false)
        return
      }
      readyToUpload = true
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    } finally {
      setComposerUploading(false)
      releaseUploadLock()
    }
    if (readyToUpload) await uploadComposerBatch(batch)
  }

  const handleComposerFileSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    const entries = Array.from(event.target.files || []).map((file) => ({ file, relativePath: file.name }))
    await handleComposerPickedFiles('files', entries)
    event.target.value = ''
  }

  const handleComposerFolderSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    await handleComposerPickedFiles('folder', buildFolderFiles(event.target.files))
    event.target.value = ''
  }

  const insertSkillPrompt = (skillName: string) => {
    const text = `请使用 ${skillName} skill。`
    updateDraft(draft.trim() ? `${draft}\n${text}` : text)
    setComposerMenuOpen(false)
  }

  const runSessionCompact = async (sessionId: string, projectIdForList: string | null) => {
    clearFailedRun(sessionId)
    let startedAfterSeq = latestEventSeq(liveEventsBySession[sessionId] || [])
    let requestId = ''
    try {
      const data = await api.getSessionEvents(sessionId)
      startedAfterSeq = latestEventSeq(data.events)
      setLiveEventsBySession((current) => ({ ...current, [sessionId]: data.events }))
    } catch {
      // Events are optional; compact status polling still works without the initial snapshot.
    }
    const startingRuns = {
      ...runningSessionsRef.current,
      [sessionId]: { requestId: '', status: 'starting', startedAfterSeq, operation: 'compact' },
    } as Record<string, RunningSession>
    runningSessionsRef.current = startingRuns
    setRunningSessions(startingRuns)
    setNotice(null)
    try {
      const run = await api.compactSession(sessionId)
      requestId = run.request_id
      const activeRuns = {
        ...runningSessionsRef.current,
        [sessionId]: { requestId: run.request_id, status: 'running', startedAfterSeq, operation: 'compact' },
      } as Record<string, RunningSession>
      runningSessionsRef.current = activeRuns
      setRunningSessions(activeRuns)
      while (true) {
        const status = await api.getChatStatus(run.request_id)
        await refreshLiveEvents(sessionId)
        if (status.status === 'running') {
          await new Promise((resolve) => window.setTimeout(resolve, 1000))
          continue
        }
        if (status.status === 'failed') {
          throw new Error(status.error || '上下文压缩失败')
        }
        if (status.status === 'interrupted') {
          setNotice('上下文压缩已中断。')
        } else {
          setNotice(status.response || '上下文已压缩。')
        }
        break
      }
      if (selectedSessionIdRef.current === sessionId) {
        await loadSessionDetail(sessionId, { preserveScroll: true, finishLiveRun: true })
      }
      await loadSessions(projectIdForList)
      await refreshLiveEvents(sessionId)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      if (requestId) {
        await refreshLiveEvents(sessionId)
        if (selectedSessionIdRef.current === sessionId) {
          await loadSessionDetail(sessionId, { preserveScroll: true })
        }
        await loadSessions(projectIdForList)
        setFailedRunsBySession((current) => ({
          ...current,
          [sessionId]: { requestId, startedAfterSeq, error: message, operation: 'compact' },
        }))
      }
      setNotice(message === 'Not Found' ? '会话或接口不存在，请刷新后重新选择会话。' : message)
    } finally {
      await refreshProjectKnowledgeBaseStatus(projectIdForList)
      const remainingRuns = withoutSession(runningSessionsRef.current, sessionId)
      runningSessionsRef.current = remainingRuns
      setRunningSessions(remainingRuns)
      const queuedMessage = popQueuedSessionMessage(sessionId)
      if (queuedMessage) {
        window.setTimeout(() => void runSessionMessage(sessionId, queuedMessage.content, projectIdForList), 0)
      }
    }
  }

  const startCompact = async () => {
    setComposerMenuOpen(false)
    if (!selectedSessionId) {
      setNotice('请先选择或创建会话。')
      return
    }
    if (runningSessions[selectedSessionId]) {
      setNotice('当前会话正在运行，请结束后再压缩上下文。')
      return
    }
    await runSessionCompact(selectedSessionId, selectedProjectId)
  }

  const startRetrospective = async (scope: 'session' | 'project') => {
    setComposerMenuOpen(false)
    if (!selectedProjectId) {
      setNotice('请先选择项目。')
      return
    }
    if (scope === 'session' && !selectedSessionId) {
      setNotice('请先选择需要复盘的会话。')
      return
    }

    setRetrospectiveStarting(true)
    setNotice(null)
    try {
      const result = await api.startRetrospective({
        project_id: selectedProjectId,
        scope,
        ...(scope === 'session' && selectedSessionId ? { source_session_id: selectedSessionId } : {}),
      })
      await loadSessions(selectedProjectId, result.session.id)
      setSelectedSessionId(result.session.id)
      setView('chat')
      setNotice(scope === 'session' ? '已开始复盘此会话。' : '已开始复盘此项目。')
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    } finally {
      setRetrospectiveStarting(false)
    }
  }

  const sendMessage = async () => {
    const content = draft.trim()
    if (!content) return
    if (!selectedSessionId && !selectedProjectId) {
      setNotice('请先新建或选择项目。')
      return
    }

    let sessionId = selectedSessionId
    const projectIdForList = selectedProjectId
    if (!sessionId && selectedProjectId) {
      const session = await createSessionForProject(selectedProjectId)
      sessionId = session.id
    }
    if (!sessionId) return

    const activeRun = runningSessionsRef.current[sessionId]
    if (activeRun?.operation === 'compact') {
      setNotice('正在压缩上下文，请结束后再发送消息。')
      return
    }

    const nextDraft = draftAfterSend(alignmentEnabledRef.current)
    draftRef.current = nextDraft
    setDraft(nextDraft)
    const sessionDraftKey = draftKeyFor(projectIdForList, sessionId)
    if (sessionDraftKey) {
      draftKeyRef.current = sessionDraftKey
      writeLocalValue(sessionDraftKey, nextDraft || null)
    }
    focusComposer(nextDraft.length)

    if (activeRun) {
      enqueueSessionMessage(sessionId, content, activeRun.status === 'stopping')
      setNotice(null)
      return
    }

    const pausedQueue = messageQueuesRef.current[sessionId]
    if (pausedQueue?.paused) {
      updateSessionMessageQueue(sessionId, resumeMessageQueue)
    }

    if (selectedSessionIdRef.current === sessionId) {
      await loadSessionDetail(sessionId, { preserveScroll: true })
    }
    appendPendingUserMessage(sessionId, content)
    await runSessionMessage(sessionId, content, projectIdForList)
  }

  const send = (event: FormEvent) => {
    event.preventDefault()
    void sendMessage()
  }

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    void sendMessage()
  }

  const continueQueuedMessages = () => {
    if (!selectedSessionId || runningSessionsRef.current[selectedSessionId]) return
    updateSessionMessageQueue(selectedSessionId, resumeMessageQueue)
    const queuedMessage = popQueuedSessionMessage(selectedSessionId)
    if (queuedMessage) {
      void runSessionMessage(selectedSessionId, queuedMessage.content, selectedProjectId)
    }
  }

  const confirmWithdrawQueuedMessage = () => {
    if (!queuedMessageToWithdraw) return
    const queue = messageQueuesRef.current[queuedMessageToWithdraw.sessionId]
    if (!queue?.items.some((message) => message.id === queuedMessageToWithdraw.message.id)) {
      setQueuedMessageToWithdraw(null)
      setNotice('该消息已经开始处理，无法撤回。')
      return
    }
    updateSessionMessageQueue(
      queuedMessageToWithdraw.sessionId,
      (queue) => withdrawQueuedMessage(queue, queuedMessageToWithdraw.message.id),
    )
    setQueuedMessageToWithdraw(null)
  }

  const handleQueuedMessageDragStart = (event: ReactDragEvent<HTMLElement>, messageId: string) => {
    setDraggedQueuedMessageId(messageId)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', messageId)
  }

  const handleQueuedMessageDragOver = (event: ReactDragEvent<HTMLDivElement>, targetId: string) => {
    if (!draggedQueuedMessageId || draggedQueuedMessageId === targetId) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    const bounds = event.currentTarget.getBoundingClientRect()
    const placement = event.clientY < bounds.top + bounds.height / 2 ? 'before' : 'after'
    setQueueDropTarget({ id: targetId, placement })
  }

  const handleQueuedMessageDrop = (event: ReactDragEvent<HTMLDivElement>, targetId: string) => {
    event.preventDefault()
    if (selectedSessionId && draggedQueuedMessageId) {
      const placement = queueDropTarget?.id === targetId ? queueDropTarget.placement : 'before'
      updateSessionMessageQueue(
        selectedSessionId,
        (queue) => moveQueuedMessage(queue, draggedQueuedMessageId, targetId, placement),
      )
    }
    setDraggedQueuedMessageId(null)
    setQueueDropTarget(null)
  }

  const handleQueuedMessageDragEnd = () => {
    setDraggedQueuedMessageId(null)
    setQueueDropTarget(null)
  }

  const stopRun = async () => {
    if (!selectedSessionId || !selectedRun) return
    updateSessionMessageQueue(selectedSessionId, pauseMessageQueue)
    const stoppingRuns = {
      ...runningSessionsRef.current,
      [selectedSessionId]: { ...selectedRun, status: 'stopping' } as RunningSession,
    }
    runningSessionsRef.current = stoppingRuns
    setRunningSessions(stoppingRuns)
    await api.interrupt(selectedSessionId)
  }

  const saveSettings = async (patch: Partial<SettingsType>) => {
    setSettings(await api.updateSettings(patch))
  }

  const saveApiSettings = async (event: FormEvent) => {
    event.preventDefault()
    const next = await api.updateSettings({
      llm_provider: apiDraft.llm_provider,
      llm_base_url: apiDraft.llm_base_url,
      llm_model_name: apiDraft.llm_model_name,
      llm_api_key: apiDraft.llm_api_key || undefined,
    })
    setSettings(next)
    setApiDraft((current) => ({ ...current, llm_api_key: next.llm_api_key }))
    setNotice('LLM API 设置已保存。')
  }

  const copyApiKey = async () => {
    if (!apiDraft.llm_api_key) return
    await navigator.clipboard.writeText(apiDraft.llm_api_key)
    setNotice('API Key 已复制。')
  }

  const updateUser = async () => {
    const name = window.prompt('显示名称', users[0]?.name || 'Local Admin')
    if (!name?.trim()) return
    const user = await api.updateCurrentUser({ name: name.trim() })
    setUsers([user])
  }

  const toggleCenterView = (nextView: Exclude<CenterView, 'chat'>) => {
    setView((current) => (current === nextView ? 'chat' : nextView))
  }

  const centerTitle =
    view === 'chat'
      ? sessionDetail?.title || '对话'
      : view === 'settings'
        ? '设置'
        : view === 'users'
          ? '用户'
          : view === 'capabilities'
            ? '能力'
            : 'API'

  return (
    <div
      className={`app-shell ${draggingPane ? 'is-resizing' : ''}`}
      style={{ gridTemplateColumns: shellGridColumns }}
    >
      <aside className="sidebar">
        <div className="brand-row">
          <img src={sandroneIcon} alt="" className="brand-icon" />
          <div>
            <strong>Sandrone beta1</strong>
            <span>Next-era workspace</span>
          </div>
        </div>

        <div className="sidebar-scroll">
          <div className="quick-actions">
            <button title="新对话" onClick={() => void createSession()}>
              <MessageSquarePlus size={18} />
              <span>新对话</span>
            </button>
            <button title="查看 Skill 和 MCP" onClick={() => toggleCenterView('capabilities')}>
              <Wrench size={18} />
              <span>能力</span>
            </button>
            <button title="API 接入" onClick={() => toggleCenterView('api')}>
              <KeyRound size={18} />
              <span>API</span>
            </button>
            <button title="用户管理" onClick={() => toggleCenterView('users')}>
              <UserRound size={18} />
              <span>用户</span>
            </button>
          </div>

          <div className="sidebar-panels">
            <div className="sidebar-section">
              <div className="section-title">
                <span>项目</span>
                <div className="menu-anchor">
                  <button title="新建项目" className="icon-button" onClick={() => setProjectMenuOpen((value) => !value)}>
                    <Plus size={16} />
                  </button>
                  {projectMenuOpen && (
                    <div className="popover-menu">
                      <button onClick={() => void createProject('managed')}>新建空项目</button>
                      <button onClick={() => void createProject('external')}>使用现有文件夹</button>
                    </div>
                  )}
                </div>
              </div>
              <div className="sidebar-panel-body">
                <div className="project-list">
                  {projects.map((project) => (
                    <div
                      key={project.id}
                      className={`project-item ${project.id === selectedProjectId ? 'active' : ''}`}
                    >
                      <button
                        className="item-main"
                        onClick={() => {
                          setSelectedProjectId(project.id)
                          setView('chat')
                        }}
                      >
                        <div className="item-title">
                          {project.is_pinned && <Pin size={12} className="item-pin-mark" />}
                          <strong>{project.name}</strong>
                        </div>
                        <span>{shortPath(project.workspace_path)}</span>
                      </button>
                      <div className="item-actions">
                        <button
                          className={`item-action ${project.is_pinned ? 'active' : ''}`}
                          title={project.is_pinned ? '取消置顶项目' : '置顶项目'}
                          onClick={() => void toggleProjectPinned(project)}
                        >
                          <Pin size={14} />
                        </button>
                        {!project.is_knowledge_base && (
                          <KnowledgeBaseProjectAction
                            project={project}
                            busy={initializingKnowledgeBaseProjectId !== null}
                            onInitialize={(target) => void initializeKnowledgeBase(target)}
                          />
                        )}
                        <button className="item-action" title="重命名项目" onClick={() => void renameProject(project)}>
                          <Pencil size={14} />
                        </button>
                        <button className="item-delete" title="删除项目" onClick={() => void deleteProject(project)}>
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </div>
                  ))}
                  {!projects.length && <div className="empty">暂无项目</div>}
                </div>
              </div>
            </div>

            <div className="sidebar-section sessions">
              <div className="section-title">
                <span>会话</span>
              </div>
              <div className="sidebar-panel-body">
                <div className="session-list">
                  {sessions.map((session) => (
                    <div
                      key={session.id}
                      className={`session-item ${session.id === selectedSessionId ? 'active' : ''}`}
                    >
                      <button
                        className="item-main"
                        onClick={() => {
                          setSelectedSessionId(session.id)
                          setView('chat')
                        }}
                      >
                        <span className="item-title">
                          {session.is_pinned && <Pin size={12} className="item-pin-mark" />}
                          <span>{session.title}</span>
                          {hasPendingPermission(runningSessions[session.id]) && (
                            <span className="permission-badge" title="此会话正在等待权限确认">
                              <ShieldCheck size={12} />
                              待确认
                            </span>
                          )}
                        </span>
                        <small>{formatTime(session.updated_at)}</small>
                      </button>
                      <div className="item-actions">
                        <button
                          className={`item-action ${session.is_pinned ? 'active' : ''}`}
                          title={session.is_pinned ? '取消置顶会话' : '置顶会话'}
                          onClick={() => void toggleSessionPinned(session)}
                        >
                          <Pin size={14} />
                        </button>
                        <button className="item-action" title="重命名会话" onClick={() => openRenameSession(session)}>
                          <Pencil size={14} />
                        </button>
                        <button className="item-delete" title="删除会话" onClick={() => void deleteSession(session)}>
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </div>
                  ))}
                  {!sessions.length && <div className="empty">暂无会话</div>}
                </div>
              </div>
            </div>
          </div>
        </div>

        <button className="settings-entry" onClick={() => toggleCenterView('settings')}>
          <Settings size={18} />
          <span>设置</span>
        </button>
      </aside>

      <button
        type="button"
        className="shell-resizer"
        title="拖动调整左侧栏宽度"
        aria-label="拖动调整左侧栏宽度"
        onMouseDown={startSidebarResize}
      />

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">{selectedProject?.name || '未选择项目'}</p>
            <h1>{centerTitle}</h1>
          </div>
          <div className="top-actions">
            {selectedProject && <span className="workspace-chip">{shortPath(selectedProject.workspace_path)}</span>}
            <button title="打开文件预览" className="icon-button large" onClick={() => setDrawerOpen(true)}>
              <PanelRightOpen size={19} />
            </button>
          </div>
        </header>

        {notice && <div className={`notice ${isDangerNotice(notice) ? 'danger' : ''}`}>{notice}</div>}

        {view === 'chat' && (
          <section className={`chat-view ${drawerOpen ? 'chat-view--compressed' : ''}`}>
            <div
              className={`message-stream ${showEmptyState ? 'empty-state-active' : ''}`}
              ref={messageStreamRef}
              onScroll={handleMessageStreamScroll}
            >
              {chatTurns.map((turn, turnIndex) => {
                const hasAttachedLiveRun = Boolean(
                  currentLiveWindow
                  && liveRunAttachedToChat
                  && attachesLiveRunToTurn(currentLiveWindow.operation, turnIndex, chatTurns.length),
                )
                const processItems = mergeProcessPresentation(
                  turn.steps,
                  hasAttachedLiveRun ? visibleLiveEvents : [],
                )
                const visibleProcessItems = hasAttachedLiveRun ? processItems.slice(-8) : processItems
                const assistantText = hasAttachedLiveRun
                  ? displayedAssistantText(currentStreamText, turn.assistant ? messageText(turn.assistant) : '')
                  : turn.assistant ? messageText(turn.assistant) : ''

                return (
                  <article key={turn.key} className="chat-turn">
                    {turn.user && (
                      <div className="message user">
                        <div className="message-role">USER</div>
                        <pre>{messageText(turn.user)}</pre>
                      </div>
                    )}
                    <div className="assistant-stack">
                      {processItems.length > 0 && (
                        <details className={`process-group ${hasAttachedLiveRun ? 'live' : ''} ${hasAttachedLiveRun && isShowingFailedRun ? 'failed' : ''}`}>
                          <summary>
                            {hasAttachedLiveRun ? (
                              <span className="live-summary-content">
                                {!isShowingFailedRun && <span className="spinner" />}
                                <span>{summarizeLiveStatus(currentRunEvents)}</span>
                              </span>
                            ) : summarizeStepList(turn.steps)}
                          </summary>
                          <div className="process-list">
                            {visibleProcessItems.map((item) => (
                              <div key={item.key} className="process-item">
                                {item.kind === 'message' ? (
                                  <>
                                    <div className="process-item-title">{processSummary(item.message)}</div>
                                    <pre>{renderProcessContent(item.message)}</pre>
                                  </>
                                ) : (
                                  <>
                                    <div className="process-item-title">{eventSummary(item.event)}</div>
                                    <pre>{eventDetails(item.event)}</pre>
                                  </>
                                )}
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                      {hasAttachedLiveRun && processItems.length === 0 && (
                        <div className={`thinking-line ${isShowingFailedRun && !isShowingRecoverableRun ? 'failed' : ''}`}>
                          {!isShowingFailedRun && <span className="spinner" />}
                          <span>{summarizeLiveStatus(currentRunEvents)}</span>
                        </div>
                      )}
                      {assistantText && (
                        <div className={`message assistant ${hasAttachedLiveRun && currentStreamText ? 'streaming' : ''}`}>
                          <div className="message-role">ASSISTANT</div>
                          <div
                            className="message-body"
                            dangerouslySetInnerHTML={{ __html: renderMarkdown(assistantText) }}
                          />
                        </div>
                      )}
                      {hasAttachedLiveRun && isShowingFailedRun && currentFailedRun && (
                        <div className={`message assistant ${isShowingRecoverableRun ? 'run-recoverable' : 'run-error'}`}>
                          <div className="message-role">SYSTEM</div>
                          <div className="message-body">{formatRunFailureMessage(currentFailedRun)}</div>
                        </div>
                      )}
                    </div>
                  </article>
                )
              })}
              {currentLiveWindow && !liveRunAttachedToChat && (
                <div className="assistant-stack live-stack">
                  {currentStreamText && (
                    <div className="message assistant streaming">
                      <div className="message-role">ASSISTANT</div>
                      <div
                        className="message-body"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(currentStreamText) }}
                      />
                    </div>
                  )}
                  {visibleLiveEvents.length ? (
                    <details className={`process-group live ${isShowingFailedRun ? 'failed' : ''}`}>
                      <summary>
                        <span className="live-summary-content">
                          {!isShowingFailedRun && <span className="spinner" />}
                          <span>{summarizeLiveStatus(visibleLiveEvents)}</span>
                        </span>
                      </summary>
                      <div className="process-list">
                        {visibleLiveEvents.slice(-8).map((event) => (
                          <div key={`${event.session_id}-${event.seq}`} className="process-item">
                            <div className="process-item-title">{eventSummary(event)}</div>
                            <pre>{eventDetails(event)}</pre>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : (
                    <div className={`thinking-line ${isShowingFailedRun && !isShowingRecoverableRun ? 'failed' : ''}`}>
                      {!isShowingFailedRun && <span className="spinner" />}
                      <span>{summarizeLiveStatus(currentRunEvents)}</span>
                    </div>
                  )}
                  {isShowingFailedRun && currentFailedRun && (
                    <div className={`message assistant ${isShowingRecoverableRun ? 'run-recoverable' : 'run-error'}`}>
                      <div className="message-role">SYSTEM</div>
                      <div className="message-body">{formatRunFailureMessage(currentFailedRun)}</div>
                    </div>
                  )}
                </div>
              )}
              {showEmptyState && (
                <div className="empty large">{currentEmptyStateQuote || EMPTY_STATE_QUOTES[0]}</div>
              )}
            </div>
            <form className="composer composer-command" onSubmit={send}>
              {currentPendingPermission && (
                <section className="permission-card" aria-live="polite">
                  <div className="permission-card-heading">
                    <span className="permission-card-icon"><ShieldCheck size={18} /></span>
                    <div>
                      <strong>需要你的权限确认</strong>
                      <span>{currentPendingPermission.tool} · {permissionRiskLabel(currentPendingPermission.risk_level)}</span>
                    </div>
                    <time>剩余 {formatPermissionCountdown(currentPermissionSeconds)}</time>
                  </div>
                  <div className="permission-card-detail">
                    <span>{currentPendingPermission.summary_label}</span>
                    <pre>{currentPendingPermission.summary}</pre>
                  </div>
                  {currentPendingPermission.reason && (
                    <p className="permission-card-reason">原因：{currentPendingPermission.reason}</p>
                  )}
                  <textarea
                    className="permission-instruction"
                    value={permissionInstruction}
                    maxLength={4000}
                    placeholder="可选：告诉 AI 改用什么方式，然后点击“追加说明后重试”"
                    onChange={(event) => setPermissionInstruction(event.target.value)}
                    disabled={permissionSubmittingId === currentPendingPermission.permission_id}
                    rows={2}
                  />
                  {permissionError && <div className="permission-error">{permissionError}</div>}
                  <div className="permission-actions">
                    <button
                      type="button"
                      className="secondary"
                      disabled={Boolean(permissionSubmittingId)}
                      onClick={() => void submitPermissionDecision('retry_with_context')}
                    >
                      追加说明后重试
                    </button>
                    <button
                      type="button"
                      className="danger"
                      disabled={Boolean(permissionSubmittingId)}
                      onClick={() => void submitPermissionDecision('deny')}
                    >
                      拒绝
                    </button>
                    <button
                      type="button"
                      disabled={Boolean(permissionSubmittingId)}
                      onClick={() => void submitPermissionDecision('allow_once')}
                    >
                      {permissionSubmittingId ? '处理中...' : '允许一次'}
                    </button>
                  </div>
                </section>
              )}
              <input ref={composerFileInputRef} type="file" multiple hidden onChange={(event) => void handleComposerFileSelect(event)} />
              <input
                ref={composerFolderInputRef}
                type="file"
                multiple
                hidden
                {...({ directory: '', webkitdirectory: '' } as Record<string, string>)}
                onChange={(event) => void handleComposerFolderSelect(event)}
              />
              {composerMenuOpen && (
                <div ref={composerMenuRef} className="composer-plus-menu">
                  <div className="composer-menu-section">添加</div>
                  <button
                    type="button"
                    disabled={!selectedProject || composerUploading}
                    onClick={() => {
                      setComposerMenuOpen(false)
                      composerFileInputRef.current?.click()
                    }}
                  >
                    <strong>上传文件</strong>
                    <span>导入一个或多个文件到项目根目录</span>
                  </button>
                  <button
                    type="button"
                    disabled={!selectedProject || composerUploading}
                    onClick={() => {
                      setComposerMenuOpen(false)
                      composerFolderInputRef.current?.click()
                    }}
                  >
                    <strong>上传文件夹</strong>
                    <span>保留文件夹内的相对路径</span>
                  </button>
                  <div className="composer-menu-section">上下文</div>
                  <button type="button" disabled={!selectedSessionId || Boolean(selectedRun)} onClick={() => void startCompact()}>
                    <strong>手动压缩上下文</strong>
                    <span>立即整理当前会话的模型上下文</span>
                  </button>
                  <div className="composer-menu-section">复盘</div>
                  <button
                    type="button"
                    disabled={!selectedSessionId || retrospectiveStarting}
                    onClick={() => void startRetrospective('session')}
                  >
                    <strong>复盘此会话</strong>
                    <span>新建会话，总结当前会话的工作与经验</span>
                  </button>
                  <button
                    type="button"
                    disabled={!selectedProjectId || retrospectiveStarting}
                    onClick={() => void startRetrospective('project')}
                  >
                    <strong>复盘此项目</strong>
                    <span>新建会话，汇总当前项目的历史工作</span>
                  </button>
                  <div className="composer-menu-section">Skill 选择区</div>
                  {composerSkillItems.map((skill) => (
                    <button type="button" key={`${skill.kind}:${skill.name}`} onClick={() => insertSkillPrompt(skill.name)}>
                      <strong>{skill.name}</strong>
                      <span>{skill.summary || `插入“请使用 ${skill.name} skill。”`}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className={`composer-shell${currentQueuedMessages.length ? ' has-queue' : ''}`}>
                {currentQueuedMessages.length > 0 && (
                  <section className="queued-message-panel" aria-label="排队消息">
                    {currentMessageQueue.paused && (
                      <div className="queued-message-status">
                        <span>队列已暂停</span>
                        <button
                          type="button"
                          disabled={Boolean(selectedRun)}
                          onClick={continueQueuedMessages}
                        >
                          <Play size={13} />
                          继续执行
                        </button>
                      </div>
                    )}
                    <div className="queued-message-list">
                      {currentQueuedMessages.map((message, index) => {
                        const dropClass = queueDropTarget?.id === message.id
                          ? ` drop-${queueDropTarget.placement}`
                          : ''
                        return (
                          <div
                            key={message.id}
                            className={`queued-message-row${draggedQueuedMessageId === message.id ? ' is-dragging' : ''}${dropClass}`}
                            onDragOver={(event) => handleQueuedMessageDragOver(event, message.id)}
                            onDrop={(event) => handleQueuedMessageDrop(event, message.id)}
                          >
                            <button
                              type="button"
                              className="queued-message-drag"
                              title="拖动调整顺序"
                              aria-label={`拖动第 ${index + 1} 条排队消息`}
                              draggable
                              onDragStart={(event) => handleQueuedMessageDragStart(event, message.id)}
                              onDragEnd={handleQueuedMessageDragEnd}
                            >
                              <GripVertical size={15} />
                            </button>
                            <span className="queued-message-order">{index + 1}</span>
                            <span className="queued-message-content" title={message.content}>{message.content}</span>
                            <button
                              type="button"
                              className="queued-message-withdraw"
                              title="撤回排队消息"
                              aria-label={`撤回第 ${index + 1} 条排队消息`}
                              onClick={() => setQueuedMessageToWithdraw({ sessionId: selectedSessionId!, message })}
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  </section>
                )}
                <div className="composer-card">
                <textarea
                  ref={composerTextareaRef}
                  value={draft}
                  onChange={(event) => updateDraft(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                  placeholder="输入消息..."
                  rows={3}
                />
                <div className="composer-toolbar">
                  <div className="composer-left-actions">
                    <button
                      ref={composerPlusButtonRef}
                      className="composer-plus-button"
                      type="button"
                      title="添加"
                      onClick={() => setComposerMenuOpen((value) => !value)}
                    >
                      <Plus size={18} />
                    </button>
                    <button
                      className={`composer-alignment-button${alignmentEnabled ? ' is-active' : ''}`}
                      type="button"
                      title={alignmentEnabled ? '关闭对齐' : '开启对齐'}
                      aria-pressed={alignmentEnabled}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={toggleAlignment}
                    >
                      对齐
                    </button>
                    {selectedProject?.is_knowledge_base && (
                      <KnowledgeBaseComposerActions
                        key={selectedProject.id}
                        onAdd={insertKnowledgeBaseAddition}
                        onRemove={insertKnowledgeBaseRemoval}
                        onMaintain={() => void sendKnowledgeBasePrompt(MAINTAIN_KNOWLEDGE_BASE_PROMPT)}
                      />
                    )}
                  </div>
                  <span className="composer-status">{composerUploading ? '上传中...' : selectedRun?.operation === 'compact' ? '正在压缩上下文' : ''}</span>
                  <div className="composer-run-actions">
                    <button
                      className="stop-button"
                      type="button"
                      title={selectedRun ? '停止' : '暂无运行'}
                      disabled={!selectedRun}
                      onClick={() => void stopRun()}
                    >
                      <Square size={18} />
                    </button>
                    <button
                      type="submit"
                      title={selectedRun ? '排队发送' : '发送'}
                      disabled={(!selectedProjectId && !selectedSessionId) || !draft.trim() || selectedRun?.operation === 'compact'}
                    >
                      <Play size={18} />
                    </button>
                  </div>
                </div>
                </div>
              </div>
            </form>
            {queuedMessageToWithdraw && (
              <div className="modal-backdrop">
                <div className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="withdraw-queued-title">
                  <h3 id="withdraw-queued-title">撤回这条排队消息？</h3>
                  <p>撤回后不会发送给 AI。</p>
                  <div className="modal-actions">
                    <button className="secondary" type="button" onClick={() => setQueuedMessageToWithdraw(null)}>
                      取消
                    </button>
                    <button className="danger" type="button" onClick={confirmWithdrawQueuedMessage}>
                      确认撤回
                    </button>
                  </div>
                </div>
              </div>
            )}
            {sessionRename && (
              <div className="modal-backdrop">
                <form
                  className="modal-panel rename-session-modal"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="rename-session-title"
                  onSubmit={(event) => void submitRenameSession(event)}
                >
                  <h3 id="rename-session-title">重命名会话</h3>
                  <label>
                    <span>会话名称</span>
                    <input
                      autoFocus
                      maxLength={160}
                      value={sessionRename.draft}
                      disabled={sessionRename.saving}
                      onChange={(event) => setSessionRename((current) => current ? {
                        ...current,
                        draft: event.target.value,
                        error: null,
                      } : current)}
                    />
                  </label>
                  {sessionRename.error && <div className="rename-session-error">{sessionRename.error}</div>}
                  <div className="modal-actions">
                    <button
                      className="secondary"
                      type="button"
                      disabled={sessionRename.saving}
                      onClick={() => setSessionRename(null)}
                    >
                      取消
                    </button>
                    <button type="submit" disabled={sessionRename.saving}>
                      {sessionRename.saving ? '保存中...' : '保存'}
                    </button>
                  </div>
                </form>
              </div>
            )}
            {showComposerConflictDialog && (
              <div className="modal-backdrop">
                <div className="modal-panel">
                  <h3>发现重名</h3>
                  <p>项目根目录里已经有同名文件或文件夹。请选择处理方式。</p>
                  <div className="conflict-list">
                    {composerConflicts.slice(0, 6).map((item) => (
                      <div key={item.path}>{item.name}</div>
                    ))}
                    {composerConflicts.length > 6 && <div>还有更多...</div>}
                  </div>
                  <div className="modal-actions">
                    <button
                      className="secondary"
                      onClick={() => {
                        setShowComposerConflictDialog(false)
                        setComposerPendingUpload(null)
                      }}
                    >
                      取消
                    </button>
                    <button
                      className="secondary"
                      onClick={() => composerPendingUpload && void uploadComposerBatch(composerPendingUpload, 'rename')}
                    >
                      保留两份
                    </button>
                    <button onClick={() => composerPendingUpload && void uploadComposerBatch(composerPendingUpload, 'replace')}>
                      覆盖
                    </button>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {view === 'settings' && settings && (
          <section className="panel-content">
            <label>
              <span>权限模式</span>
              <select
                value={settings.permission_mode}
                onChange={(event) => void saveSettings({ permission_mode: event.target.value })}
              >
                <option value="ask">ask</option>
                <option value="auto">auto</option>
              </select>
            </label>
            <label>
              <span>主题</span>
              <select value={settings.theme} onChange={(event) => void saveSettings({ theme: event.target.value })}>
                <option value="light">light</option>
                <option value="dark">dark</option>
                <option value="system">system</option>
              </select>
            </label>
          </section>
        )}

        {view === 'users' && (
          <section className="panel-content">
            {users.map((user) => (
              <button key={user.id} className="wide-row" onClick={() => void updateUser()}>
                <UserRound size={18} />
                <strong>{user.name}</strong>
                <span>{user.role}</span>
              </button>
            ))}
            <button className="wide-row muted">
              <ShieldCheck size={18} />
              <strong>本地权限</strong>
              <span>admin 可管理项目、设置和会话</span>
            </button>
          </section>
        )}

        {view === 'capabilities' && (
          <section className="panel-content">
            {capabilities.map((item) => (
              <div key={`${item.kind}-${item.path}-${item.name}`} className="capability-row">
                <Code2 size={18} />
                <div>
                  <strong>{item.name}</strong>
                  <p>{item.summary || item.path}</p>
                </div>
                <span>{item.kind}</span>
              </div>
            ))}
            {!capabilities.length && <div className="empty">没有扫描到 skill 或 MCP</div>}
          </section>
        )}

        {view === 'api' && (
          <form className="panel-content" onSubmit={(event) => void saveApiSettings(event)}>
            <label>
              <span>Provider</span>
              <select
                value={apiDraft.llm_provider}
                onChange={(event) => {
                  const provider = event.target.value as SettingsType['llm_provider']
                  setApiDraft((current) => ({
                    ...current,
                    llm_provider: provider,
                    llm_api_key: settings?.llm_api_keys?.[provider] || '',
                  }))
                }}
              >
                <option value="openai">OpenAI</option>
                <option value="deepseek">DeepSeek</option>
                <option value="minimax">MiniMax</option>
                <option value="zhipu">Zhipu</option>
                <option value="kimi">Kimi</option>
                <option value="siliconflow">SiliconFlow</option>
                <option value="custom">自定义</option>
              </select>
            </label>
            <label>
              <span>Base URL</span>
              <input
                value={apiDraft.llm_base_url}
                onChange={(event) => setApiDraft((current) => ({ ...current, llm_base_url: event.target.value }))}
                placeholder="https://api.openai.com/v1"
              />
            </label>
            <label>
              <span>API Key</span>
              <div className="secret-input">
                <input
                  type={apiKeyVisible ? 'text' : 'password'}
                  value={apiDraft.llm_api_key}
                  onChange={(event) => setApiDraft((current) => ({ ...current, llm_api_key: event.target.value }))}
                  placeholder="输入或粘贴 API Key"
                />
                <button type="button" title={apiKeyVisible ? '隐藏 API Key' : '查看 API Key'} onClick={() => setApiKeyVisible((value) => !value)}>
                  {apiKeyVisible ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
                <button type="button" title="复制 API Key" disabled={!apiDraft.llm_api_key} onClick={() => void copyApiKey()}>
                  <Copy size={16} />
                </button>
              </div>
            </label>
            <label>
              <span>Model</span>
              <input
                value={apiDraft.llm_model_name}
                onChange={(event) => setApiDraft((current) => ({ ...current, llm_model_name: event.target.value }))}
                placeholder="gpt-4.1 / MiniMax-M2.5 / kimi-k2"
              />
            </label>
            <div className="api-status">
              <span>{apiDraft.llm_api_key ? '当前 Provider 已保存 API Key' : '当前 Provider 还没有 API Key'}</span>
              <button type="submit">保存 API 设置</button>
            </div>
          </form>
        )}
      </main>

      <FileDrawer
        project={selectedProject}
        open={drawerOpen}
        width={drawerWidth}
        refreshKey={fileDrawerRefreshKey}
        onResizeStart={startDrawerResize}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  )
}

