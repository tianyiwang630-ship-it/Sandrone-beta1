export function excludeDeletedSessions<T extends { id: string }>(sessions: T[], deletedSessionIds: Set<string>) {
  if (!deletedSessionIds.size) return sessions
  return sessions.filter((session) => !deletedSessionIds.has(session.id))
}
