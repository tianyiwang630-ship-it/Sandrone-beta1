export function remainingPermissionSeconds(expiresAt: string, now = Date.now()) {
  const expires = Date.parse(expiresAt)
  if (!Number.isFinite(expires)) return 0
  return Math.max(0, Math.ceil((expires - now) / 1000))
}

export function isRetryInstructionValid(instruction: string) {
  return Boolean(instruction.trim())
}

export function hasPendingPermission(
  run: { pendingPermission?: unknown | null } | null | undefined,
) {
  return Boolean(run?.pendingPermission)
}
