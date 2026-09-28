interface StoredSteeringAttempt {
  content: string
  messageId: string
}

type StorageLike = Pick<Storage, 'length' | 'key' | 'getItem' | 'setItem' | 'removeItem'>

const storageKeyForSession = (sessionId: string) => (
  `sandrone:steer-attempt:v2:${encodeURIComponent(sessionId)}`
)

const legacyStoragePrefix = (sessionId: string) => (
  `sandrone:steer-attempt:${encodeURIComponent(sessionId)}:`
)

function readAttempts(storage: StorageLike, storageKey: string): StoredSteeringAttempt[] {
  try {
    const parsed = JSON.parse(storage.getItem(storageKey) || '[]') as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter((value): value is StoredSteeringAttempt => (
      typeof value === 'object' && value !== null
      && 'content' in value && typeof value.content === 'string'
      && 'messageId' in value && typeof value.messageId === 'string'
    ))
  } catch {
    return []
  }
}

function writeAttempts(storage: StorageLike, storageKey: string, attempts: StoredSteeringAttempt[]) {
  try {
    if (attempts.length) storage.setItem(storageKey, JSON.stringify(attempts))
    else storage.removeItem(storageKey)
  } catch {
    // Retry state is a convenience cache; the in-memory attempt still works.
  }
}

export function steeringDraftAttemptKey(sessionId: string, content: string) {
  return JSON.stringify([sessionId, content])
}

export function loadSteeringDraftAttempt(
  storage: StorageLike | null,
  sessionId: string,
  content: string,
): string | null {
  if (!storage) return null
  const storageKey = storageKeyForSession(sessionId)
  const attempts = readAttempts(storage, storageKey)
  const savedAttempt = attempts.find((attempt) => attempt.content === content)
  if (savedAttempt) return savedAttempt.messageId

  const legacyPrefix = legacyStoragePrefix(sessionId)
  try {
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const legacyKey = storage.key(index)
      if (!legacyKey?.startsWith(legacyPrefix)) continue
      const saved = JSON.parse(storage.getItem(legacyKey) || 'null') as Partial<StoredSteeringAttempt> | null
      if (saved?.content !== content || typeof saved.messageId !== 'string') continue
      writeAttempts(storage, storageKey, [...attempts, { content, messageId: saved.messageId }])
      try { storage.removeItem(legacyKey) } catch { /* Keep the migrated attempt if cleanup fails. */ }
      return saved.messageId
    }
  } catch {
    return null
  }
  return null
}

export function saveSteeringDraftAttempt(
  storage: StorageLike | null,
  sessionId: string,
  content: string,
  messageId: string,
) {
  if (!storage) return
  const storageKey = storageKeyForSession(sessionId)
  const attempts = readAttempts(storage, storageKey)
    .filter((attempt) => attempt.content !== content)
  writeAttempts(storage, storageKey, [...attempts, { content, messageId }])
}

export function clearSteeringDraftAttempt(
  storage: StorageLike | null,
  sessionId: string,
  content: string,
  messageId: string,
) {
  if (!storage) return
  const storageKey = storageKeyForSession(sessionId)
  const attempts = readAttempts(storage, storageKey)
    .filter((attempt) => attempt.content !== content || attempt.messageId !== messageId)
  writeAttempts(storage, storageKey, attempts)

  const legacyPrefix = legacyStoragePrefix(sessionId)
  try {
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const legacyKey = storage.key(index)
      if (!legacyKey?.startsWith(legacyPrefix)) continue
      const saved = JSON.parse(storage.getItem(legacyKey) || 'null') as Partial<StoredSteeringAttempt> | null
      if (saved?.content === content && saved.messageId === messageId) storage.removeItem(legacyKey)
    }
  } catch {
    // The current retry marker is already cleared from the session record.
  }
}
