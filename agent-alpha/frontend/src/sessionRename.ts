import type { Session, SessionDetail } from './types'

export function validateSessionTitle(value: string, currentTitle: string): string | null {
  const title = value.trim()
  if (!title || title === currentTitle || title.length > 160) return null
  return title
}

export function replaceSessionSummary(sessions: Session[], updated: Session): Session[] {
  return sessions.map((session) => session.id === updated.id ? updated : session)
}

export function mergeSessionDetail(
  detail: SessionDetail | null,
  updated: Session,
): SessionDetail | null {
  if (!detail || detail.id !== updated.id) return detail
  return { ...detail, ...updated }
}
