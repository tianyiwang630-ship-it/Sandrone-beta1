import {
  Code2,
  Copy,
  Eye,
  EyeOff,
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
import sandroneIcon from './assets/sandrone-icon.png'
import FileDrawer from './components/FileDrawer'
import { EMPTY_STATE_QUOTES } from './emptyStateQuotes'
import type {
  CapabilityItem,
  Message,
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
}

interface FailedRunSnapshot {
  requestId: string
  startedAfterSeq: number
  error: string
  operation?: 'chat' | 'compact'
  recoverable?: boolean
}

const FALLBACK_COMPOSER_SKILLS: CapabilityItem[] = [
  { name: 'ljg-paper', kind: 'skill', path: '', summary: '论文阅读和结构化讲解' },
  { name: 'ljg-plain', kind: 'skill', path: '', summary: '把复杂内容讲成白话' },
  { name: 'pdf', kind: 'skill', path: '', summary: '读取、拆分、合并或生成 PDF' },
]

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

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeAttribute(value: string) {
  return escapeHtml(value).replace(/`/g, '&#96;')
}

function isSafeHref(value: string) {
  return /^(https?:|mailto:)/i.test(value)
}

function formatInlineMarkdown(value: string) {
  const codeTokens: string[] = []
  let html = escapeHtml(value).replace(/`([^`\n]+)`/g, (_match: string, code: string) => {
    const token = `@@CODETOKEN${codeTokens.length}@@`
    codeTokens.push(`<code>${code}</code>`)
    return token
  })

  html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match: string, label: string, href: string) => {
    if (!isSafeHref(href)) return label
    return `<a href="${escapeAttribute(href)}" target="_blank" rel="noreferrer">${label}</a>`
  })
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
  html = html.replace(/(?<!_)_([^_\n]+)_(?!_)/g, '<em>$1</em>')
  html = html.replace(/~~([^~\n]+)~~/g, '<del>$1</del>')

  return codeTokens.reduce(
    (result, tokenHtml, index) => result.replace(`@@CODETOKEN${index}@@`, tokenHtml),
    html,
  )
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isTableSeparator(line: string) {
  const cells = splitTableRow(line)
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function renderMarkdownTable(lines: string[], start: number) {
  const header = splitTableRow(lines[start] || '')
  const body: string[][] = []
  let index = start + 2

  while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
    body.push(splitTableRow(lines[index]))
    index += 1
  }

  const thead = `<thead><tr>${header.map((cell) => `<th>${formatInlineMarkdown(cell)}</th>`).join('')}</tr></thead>`
  const tbody = body.length
    ? `<tbody>${body
        .map((row) => `<tr>${row.map((cell) => `<td>${formatInlineMarkdown(cell)}</td>`).join('')}</tr>`)
        .join('')}</tbody>`
    : ''

  return {
    html: `<table>${thead}${tbody}</table>`,
    nextIndex: index,
  }
}

function renderMarkdown(value: string) {
  const lines = value.replace(/\r\n/g, '\n').split('\n')
  const blocks: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] || ''
    const trimmed = line.trim()

    if (!trimmed) {
      index += 1
      continue
    }

    const codeFence = trimmed.match(/^```([\w-]+)?\s*$/)
    if (codeFence) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      const language = codeFence[1] ? ` class="language-${escapeAttribute(codeFence[1])}"` : ''
      blocks.push(`<pre><code${language}>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
      continue
    }

    if (/^\|?.+\|.+$/.test(trimmed) && index + 1 < lines.length && isTableSeparator(lines[index + 1] || '')) {
      const table = renderMarkdownTable(lines, index)
      blocks.push(table.html)
      index = table.nextIndex
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      blocks.push(`<h${level}>${formatInlineMarkdown(heading[2])}</h${level}>`)
      index += 1
      continue
    }

    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push('<hr />')
      index += 1
      continue
    }

    if (/^\s*>\s?/.test(line)) {
      const quoteLines: string[] = []
      while (index < lines.length && /^\s*>\s?/.test(lines[index] || '')) {
        quoteLines.push((lines[index] || '').replace(/^\s*>\s?/, ''))
        index += 1
      }
      const quote = quoteLines
        .join('\n')
        .split(/\n\s*\n/)
        .map((part) => `<p>${formatInlineMarkdown(part.trim().replace(/\n+/g, '<br />'))}</p>`)
        .join('')
      blocks.push(`<blockquote>${quote}</blockquote>`)
      continue
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index] || '')) {
        items.push(`<li>${formatInlineMarkdown((lines[index] || '').replace(/^\s*[-*+]\s+/, ''))}</li>`)
        index += 1
      }
      blocks.push(`<ul>${items.join('')}</ul>`)
      continue
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index] || '')) {
        items.push(`<li>${formatInlineMarkdown((lines[index] || '').replace(/^\s*\d+\.\s+/, ''))}</li>`)
        index += 1
      }
      blocks.push(`<ol>${items.join('')}</ol>`)
      continue
    }

    const paragraphLines: string[] = []
    while (index < lines.length) {
      const current = lines[index] || ''
      const currentTrimmed = current.trim()
      if (!currentTrimmed) break
      if (
        /^```/.test(currentTrimmed) ||
        /^(#{1,6})\s+/.test(current) ||
        /^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(current) ||
        /^\s*>\s?/.test(current) ||
        /^\s*[-*+]\s+/.test(current) ||
        /^\s*\d+\.\s+/.test(current) ||
        (/^\|?.+\|.+$/.test(currentTrimmed) && index + 1 < lines.length && isTableSeparator(lines[index + 1] || ''))
      ) {
        break
      }
      paragraphLines.push(currentTrimmed)
      index += 1
    }
    blocks.push(`<p>${formatInlineMarkdown(paragraphLines.join(' '))}</p>`)
  }

  return blocks.join('')
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

function shortPath(path: string) {
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
  if (parts.length <= 4) return path
  return `${parts.slice(0, 1).join('/')}/.../${parts.slice(-3).join('/')}`
}

const SELECTED_PROJECT_STORAGE_KEY = 'sandrone:selectedProjectId'
const SELECTED_SESSION_STORAGE_KEY = 'sandrone:selectedSessionId'
const DRAFT_STORAGE_PREFIX = 'sandrone:draft:'

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
  const [view, setView] = useState<CenterView>('chat')
  const [settings, setSettings] = useState<SettingsType | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [capabilities, setCapabilities] = useState<CapabilityItem[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [projectMenuOpen, setProjectMenuOpen] = useState(false)
  const [pendingMessagesBySession, setPendingMessagesBySession] = useState<Record<string, Message[]>>({})
  const [queuedMessagesBySession, setQueuedMessagesBySession] = useState<Record<string, string[]>>({})
  const [liveEventsBySession, setLiveEventsBySession] = useState<Record<string, SessionEvent[]>>({})
  const [runningSessions, setRunningSessions] = useState<Record<string, RunningSession>>({})
  const [failedRunsBySession, setFailedRunsBySession] = useState<Record<string, FailedRunSnapshot>>({})
  const [apiKeyVisible, setApiKeyVisible] = useState(false)
  const [emptyStateQuotesByKey, setEmptyStateQuotesByKey] = useState<Record<string, string>>({})
  const [composerMenuOpen, setComposerMenuOpen] = useState(false)
  const [composerUploading, setComposerUploading] = useState(false)
  const [composerConflicts, setComposerConflicts] = useState<UploadConflictItem[]>([])
  const [composerPendingUpload, setComposerPendingUpload] = useState<UploadEntry[] | null>(null)
  const [showComposerConflictDialog, setShowComposerConflictDialog] = useState(false)
  const [fileDrawerRefreshKey, setFileDrawerRefreshKey] = useState(0)
  const [sidebarWidth, setSidebarWidth] = useState(306)
  const [drawerWidth, setDrawerWidth] = useState(760)
  const [draggingPane, setDraggingPane] = useState<'sidebar' | 'drawer' | null>(null)
  const messageStreamRef = useRef<HTMLDivElement | null>(null)
  const preserveScrollTopRef = useRef<number | null>(null)
  const dragStateRef = useRef({ x: 0, sidebarWidth: 306, drawerWidth: 760 })
  const selectedProjectIdRef = useRef<string | null>(null)
  const selectedSessionIdRef = useRef<string | null>(null)
  const queuedMessagesRef = useRef<Record<string, string[]>>({})
  const runningSessionsRef = useRef<Record<string, RunningSession>>({})
  const draftKeyRef = useRef<string | null>(null)
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
  const currentQueuedMessages = selectedSessionId ? queuedMessagesBySession[selectedSessionId] || [] : []
  const currentLiveEvents = selectedSessionId ? liveEventsBySession[selectedSessionId] || [] : []
  const selectedRun = selectedSessionId ? runningSessions[selectedSessionId] || null : null
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
  const emptyStateKey = selectedSessionId || (selectedProjectId ? `project:${selectedProjectId}` : 'global')
  const currentEmptyStateQuote = emptyStateQuotesByKey[emptyStateKey]
  const showEmptyState = !displayMessages.length && !selectedRun && !currentFailedRun
  const shellGridColumns = drawerOpen
    ? `${sidebarWidth}px 8px minmax(360px, 1fr) ${drawerWidth}px`
    : `${sidebarWidth}px 8px minmax(520px, 1fr)`

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

  const loadSessions = async (projectId = selectedProjectId, preferredSessionId = selectedSessionIdRef.current) => {
    if (!projectId) {
      setSessions([])
      setSelectedSessionId(null)
      return
    }
    const data = await api.listProjectSessions(projectId)
    setSessions(data.sessions)
    setSelectedSessionId((current) => {
      if (data.sessions.some((session) => session.id === current)) return current
      if (data.sessions.some((session) => session.id === preferredSessionId)) return preferredSessionId
      const stored = readLocalValue(SELECTED_SESSION_STORAGE_KEY)
      if (data.sessions.some((session) => session.id === stored)) return stored
      return data.sessions[0]?.id || null
    })
  }

  const loadSessionDetail = async (sessionId = selectedSessionId, options: { preserveScroll?: boolean } = {}) => {
    if (!sessionId) {
      setSessionDetail(null)
      return
    }
    const nextDetail = await api.getSession(sessionId)
    if (options.preserveScroll && selectedSessionIdRef.current === sessionId) {
      preserveScrollTopRef.current = messageStreamRef.current?.scrollTop ?? null
    }
    setSessionDetail(nextDetail)
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
    setSessionDetail(null)
    void loadSessions(selectedProjectId)
  }, [selectedProjectId])

  useEffect(() => {
    selectedSessionIdRef.current = selectedSessionId
    setFailedRunsBySession({})
    void loadSessionDetail(selectedSessionId)
  }, [selectedSessionId])

  useEffect(() => {
    selectedProjectIdRef.current = selectedProjectId
    writeLocalValue(SELECTED_PROJECT_STORAGE_KEY, selectedProjectId)
  }, [selectedProjectId])

  useEffect(() => {
    writeLocalValue(SELECTED_SESSION_STORAGE_KEY, selectedSessionId)
  }, [selectedSessionId])

  useEffect(() => {
    const nextKey = draftKeyFor(selectedProjectId, selectedSessionId)
    draftKeyRef.current = nextKey
    setDraft(nextKey ? readLocalValue(nextKey) || '' : '')
  }, [selectedProjectId, selectedSessionId])

  useEffect(() => {
    queuedMessagesRef.current = queuedMessagesBySession
  }, [queuedMessagesBySession])

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
    const top = preserveScrollTopRef.current
    const stream = messageStreamRef.current
    if (top == null || !stream) return
    const maxTop = Math.max(0, stream.scrollHeight - stream.clientHeight)
    stream.scrollTop = Math.min(top, maxTop)
    preserveScrollTopRef.current = null
  }, [sessionDetail?.id, sessionDetail?.updated_at, sessionDetail?.message_count])

  useEffect(() => {
    if (!draggingPane) return

    const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

    const handleMouseMove = (event: globalThis.MouseEvent) => {
      const deltaX = event.clientX - dragStateRef.current.x
      if (draggingPane === 'sidebar') {
        const maxWidth = Math.max(320, window.innerWidth - (drawerOpen ? drawerWidth : 0) - 420)
        setSidebarWidth(clamp(dragStateRef.current.sidebarWidth + deltaX, 240, maxWidth))
        return
      }

      const maxWidth = Math.max(520, window.innerWidth - sidebarWidth - 360)
      setDrawerWidth(clamp(dragStateRef.current.drawerWidth - deltaX, 520, maxWidth))
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

  const createSessionForProject = async (projectId: string) => {
    const session = await api.createSession(projectId)
    const projectDraftKey = draftKeyFor(projectId, null)
    const sessionDraftKey = draftKeyFor(projectId, session.id)
    const projectDraft = projectDraftKey ? readLocalValue(projectDraftKey) : null
    if (projectDraft && projectDraftKey && sessionDraftKey && !readLocalValue(sessionDraftKey)) {
      writeLocalValue(sessionDraftKey, projectDraft)
      writeLocalValue(projectDraftKey, null)
    }
    await loadSessions(projectId)
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
    await api.deleteSession(session.id)
    if (selectedSessionId === session.id) {
      setSelectedSessionId(null)
      setSessionDetail(null)
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
    await loadSessions(selectedProjectId)
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

  const renameSession = async (session: Session) => {
    const title = window.prompt('会话新名称', session.title)
    if (title == null) return
    const nextTitle = title.trim()
    if (!nextTitle || nextTitle === session.title) return
    await api.updateSession(session.id, { title: nextTitle })
    await loadSessions(selectedProjectId)
    if (selectedSessionId === session.id) {
      await loadSessionDetail(session.id, { preserveScroll: true })
    }
    setNotice(`已重命名会话「${nextTitle}」`)
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

  const refreshLiveEvents = async (sessionId: string) => {
    try {
      const data = await api.getSessionEvents(sessionId)
      setLiveEventsBySession((current) => ({ ...current, [sessionId]: data.events }))
      return data.events
    } catch {
      setLiveEventsBySession((current) => ({ ...current, [sessionId]: [] }))
      return []
    }
  }

  useEffect(() => {
    if (!selectedSessionId) return
    void refreshLiveEvents(selectedSessionId)
  }, [selectedSessionId])

  const resumeActiveRun = async (sessionId: string, projectIdForList = selectedProjectIdRef.current) => {
    let activeRun
    try {
      activeRun = await api.getSessionActiveRun(sessionId)
    } catch {
      return
    }
    const existingRun = runningSessionsRef.current[sessionId]
    if (existingRun?.requestId === activeRun.request_id) return

    clearFailedRun(sessionId)
    const events = await refreshLiveEvents(sessionId)
    const startedAfterSeq = activeRun.started_after_seq ?? latestUserEventSeq(events)
    setRunningSessions((current) => ({
      ...current,
      [sessionId]: {
        requestId: activeRun.request_id,
        status: 'running',
        startedAfterSeq,
        operation: activeRun.operation || 'chat',
      },
    }))

    try {
      while (true) {
        const status = await api.getChatStatus(activeRun.request_id)
        await refreshLiveEvents(sessionId)
        if (status.status === 'running') {
          await new Promise((resolve) => window.setTimeout(resolve, 1000))
          continue
        }
        if (status.status === 'failed') {
          throw new Error(status.error || '运行失败')
        }
        if (status.status === 'recoverable') {
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
        await loadSessionDetail(sessionId, { preserveScroll: true })
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
      setRunningSessions((current) => {
        const next = { ...current }
        delete next[sessionId]
        return next
      })
    }
  }

  useEffect(() => {
    if (!selectedSessionId) return
    void resumeActiveRun(selectedSessionId)
  }, [selectedSessionId])

  useEffect(() => {
    const refreshVisibleSession = () => {
      if (document.visibilityState === 'hidden' || !selectedSessionIdRef.current) return
      const sessionId = selectedSessionIdRef.current
      void loadSessionDetail(sessionId, { preserveScroll: true })
      void refreshLiveEvents(sessionId)
      void resumeActiveRun(sessionId)
    }
    window.addEventListener('focus', refreshVisibleSession)
    document.addEventListener('visibilitychange', refreshVisibleSession)
    return () => {
      window.removeEventListener('focus', refreshVisibleSession)
      document.removeEventListener('visibilitychange', refreshVisibleSession)
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

  const enqueueSessionMessage = (sessionId: string, content: string) => {
    const next = {
      ...queuedMessagesRef.current,
      [sessionId]: [...(queuedMessagesRef.current[sessionId] || []), content],
    }
    queuedMessagesRef.current = next
    setQueuedMessagesBySession(next)
  }

  const popQueuedSessionMessage = (sessionId: string) => {
    const queue = queuedMessagesRef.current[sessionId] || []
    const [nextMessage, ...rest] = queue
    if (!nextMessage) return null

    const next = { ...queuedMessagesRef.current }
    if (rest.length) next[sessionId] = rest
    else delete next[sessionId]
    queuedMessagesRef.current = next
    setQueuedMessagesBySession(next)
    return nextMessage
  }

  const updateDraft = (value: string) => {
    setDraft(value)
    if (draftKeyRef.current) {
      writeLocalValue(draftKeyRef.current, value)
    }
  }

  const runSessionMessage = async (sessionId: string, content: string, projectIdForList: string | null) => {
    clearFailedRun(sessionId)
    ensurePendingUserMessage(sessionId, content)
    let startedAfterSeq = latestEventSeq(liveEventsBySession[sessionId] || [])
    let requestId = ''
    try {
      const data = await api.getSessionEvents(sessionId)
      startedAfterSeq = latestEventSeq(data.events)
      setLiveEventsBySession((current) => ({ ...current, [sessionId]: data.events }))
    } catch {
      // Events are an optional live enhancement; chat should still start if this snapshot is unavailable.
    }
    setLiveEventsBySession((current) => ({ ...current, [sessionId]: [] }))
    setRunningSessions((current) => ({
      ...current,
      [sessionId]: { requestId: '', status: 'starting', startedAfterSeq, operation: 'chat' },
    }))
    setNotice(null)
    try {
      const run = await api.sendMessage(sessionId, content)
      requestId = run.request_id
      if (selectedSessionIdRef.current === sessionId) {
        await loadSessionDetail(sessionId, { preserveScroll: true })
      }
      removePendingUserMessage(sessionId, content)
      setRunningSessions((current) => ({
        ...current,
        [sessionId]: { requestId: run.request_id, status: 'running', startedAfterSeq, operation: 'chat' },
      }))
      while (true) {
        const status = await api.getChatStatus(run.request_id)
        await refreshLiveEvents(sessionId)
        if (status.status === 'running') {
          await new Promise((resolve) => window.setTimeout(resolve, 1000))
          continue
        }
        if (status.status === 'failed') {
          throw new Error(status.error || '运行失败')
        }
        if (status.status === 'recoverable') {
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
        await loadSessionDetail(sessionId, { preserveScroll: true })
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
      setRunningSessions((current) => {
        const next = { ...current }
        delete next[sessionId]
        return next
      })
      const queuedMessage = popQueuedSessionMessage(sessionId)
      if (queuedMessage) {
        window.setTimeout(() => void runSessionMessage(sessionId, queuedMessage, projectIdForList), 0)
      }
    }
  }

  const uploadComposerBatch = async (entries: UploadEntry[], strategy?: ConflictStrategy) => {
    if (!selectedProject || !entries.length) return
    setComposerUploading(true)
    setNotice(null)
    try {
      await uploadProjectFiles(selectedProject.id, '', entries, strategy)
      setShowComposerConflictDialog(false)
      setComposerPendingUpload(null)
      setComposerConflicts([])
      setComposerMenuOpen(false)
      setFileDrawerRefreshKey((value) => value + 1)
      setNotice(`已上传 ${entries.length} 个文件到项目根目录。`)
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    } finally {
      setComposerUploading(false)
    }
  }

  const handleComposerPickedFiles = async (entries: UploadEntry[]) => {
    if (!selectedProject) {
      setNotice('请先选择项目。')
      return
    }
    if (!entries.length) return
    try {
      const conflictData = await checkProjectUploadConflicts(selectedProject.id, '', entries)
      if (conflictData.has_conflicts) {
        setComposerPendingUpload(entries)
        setComposerConflicts(conflictData.conflicts)
        setShowComposerConflictDialog(true)
        setComposerMenuOpen(false)
        return
      }
      await uploadComposerBatch(entries)
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    }
  }

  const handleComposerFileSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    const entries = Array.from(event.target.files || []).map((file) => ({ file, relativePath: file.name }))
    await handleComposerPickedFiles(entries)
    event.target.value = ''
  }

  const handleComposerFolderSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    await handleComposerPickedFiles(buildFolderFiles(event.target.files))
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
    setRunningSessions((current) => ({
      ...current,
      [sessionId]: { requestId: '', status: 'starting', startedAfterSeq, operation: 'compact' },
    }))
    setNotice(null)
    try {
      const run = await api.compactSession(sessionId)
      requestId = run.request_id
      setRunningSessions((current) => ({
        ...current,
        [sessionId]: { requestId: run.request_id, status: 'running', startedAfterSeq, operation: 'compact' },
      }))
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
        await loadSessionDetail(sessionId, { preserveScroll: true })
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
      setRunningSessions((current) => {
        const next = { ...current }
        delete next[sessionId]
        return next
      })
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

    if (runningSessions[sessionId]?.operation === 'compact') {
      setNotice('正在压缩上下文，请结束后再发送消息。')
      return
    }

    updateDraft('')
    const sessionDraftKey = draftKeyFor(projectIdForList, sessionId)
    if (sessionDraftKey) {
      writeLocalValue(sessionDraftKey, null)
    }

    if (runningSessions[sessionId]) {
      enqueueSessionMessage(sessionId, content)
      setNotice(null)
      return
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

  const stopRun = async () => {
    if (!selectedSessionId || !selectedRun) return
    setRunningSessions((current) => ({
      ...current,
      [selectedSessionId]: { ...selectedRun, status: 'stopping' },
    }))
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
                        <button className="item-action" title="重命名会话" onClick={() => void renameSession(session)}>
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
            <div className={`message-stream ${showEmptyState ? 'empty-state-active' : ''}`} ref={messageStreamRef}>
              {chatTurns.map((turn) => (
                <article key={turn.key} className="chat-turn">
                  {turn.user && (
                    <div className="message user">
                      <div className="message-role">USER</div>
                      <pre>{messageText(turn.user)}</pre>
                    </div>
                  )}
                  <div className="assistant-stack">
                    {turn.steps.length > 0 && (
                      <details className="process-group">
                        <summary>{summarizeStepList(turn.steps)}</summary>
                        <div className="process-list">
                          {turn.steps.map((step, index) => (
                            <div key={`${turn.key}-step-${index}`} className="process-item">
                              <div className="process-item-title">{processSummary(step)}</div>
                              <pre>{renderProcessContent(step)}</pre>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                    {turn.assistant && (
                      <div className="message assistant">
                        <div className="message-role">ASSISTANT</div>
                        <div
                          className="message-body"
                          dangerouslySetInnerHTML={{ __html: renderMarkdown(messageText(turn.assistant)) }}
                        />
                      </div>
                    )}
                  </div>
                </article>
              ))}
              {currentLiveWindow && (
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
              {selectedRun &&
                currentQueuedMessages.map((content, index) => (
                  <div key={`queued-${index}`} className="message user queued">
                    <div className="message-role">USER · 已排队</div>
                    <pre>{content}</pre>
                  </div>
                ))}
              {showEmptyState && (
                <div className="empty large">{currentEmptyStateQuote || EMPTY_STATE_QUOTES[0]}</div>
              )}
            </div>
            <form className="composer composer-command" onSubmit={send}>
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
                  <div className="composer-menu-section">Skill 选择区</div>
                  {composerSkillItems.map((skill) => (
                    <button type="button" key={`${skill.kind}:${skill.name}`} onClick={() => insertSkillPrompt(skill.name)}>
                      <strong>{skill.name}</strong>
                      <span>{skill.summary || `插入“请使用 ${skill.name} skill。”`}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="composer-card">
                <textarea
                  value={draft}
                  onChange={(event) => updateDraft(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                  placeholder="输入消息..."
                  rows={3}
                />
                <div className="composer-toolbar">
                  <button
                    ref={composerPlusButtonRef}
                    className="composer-plus-button"
                    type="button"
                    title="添加"
                    onClick={() => setComposerMenuOpen((value) => !value)}
                  >
                    <Plus size={18} />
                  </button>
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
            </form>
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

