export interface ScrollStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

const CHAT_SCROLL_STORAGE_PREFIX = 'agent-alpha:chat-scroll:'

export function normalizeScrollTop(value: unknown): number {
  const numeric = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(numeric) && numeric >= 0 ? numeric : 0
}

export function clampScrollTop(scrollTop: unknown, scrollHeight: number, clientHeight: number): number {
  const maxTop = Math.max(0, normalizeScrollTop(scrollHeight) - normalizeScrollTop(clientHeight))
  return Math.min(normalizeScrollTop(scrollTop), maxTop)
}

function storageKey(sessionId: string) {
  return `${CHAT_SCROLL_STORAGE_PREFIX}${sessionId}`
}

export function readSessionScrollTop(storage: ScrollStorage | null, sessionId: string): number {
  if (!storage || !sessionId) return 0
  try {
    const raw = storage.getItem(storageKey(sessionId))
    if (!raw) return 0
    const parsed = JSON.parse(raw) as { scrollTop?: unknown }
    return normalizeScrollTop(parsed?.scrollTop)
  } catch {
    return 0
  }
}

export function writeSessionScrollTop(storage: ScrollStorage | null, sessionId: string, scrollTop: unknown) {
  if (!storage || !sessionId) return
  try {
    storage.setItem(storageKey(sessionId), JSON.stringify({ scrollTop: normalizeScrollTop(scrollTop) }))
  } catch {
    // Scroll persistence is optional; chat must keep working when storage is unavailable.
  }
}

export function removeSessionScrollTop(storage: ScrollStorage | null, sessionId: string) {
  if (!storage || !sessionId) return
  try {
    storage.removeItem(storageKey(sessionId))
  } catch {
    // Scroll persistence is optional.
  }
}

export function isCurrentSessionRequest(
  selectedSessionId: string | null,
  responseSessionId: string,
  latestRequestSequence: number,
  responseRequestSequence: number,
) {
  return selectedSessionId === responseSessionId && latestRequestSequence === responseRequestSequence
}

export function withoutSession<T>(values: Record<string, T>, sessionId: string): Record<string, T> {
  if (!(sessionId in values)) return values
  const next = { ...values }
  delete next[sessionId]
  return next
}
