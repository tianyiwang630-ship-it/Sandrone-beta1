import type { FileInfo } from './types'

export type ComposerUploadKind = 'files' | 'folder'

interface UploadPathEntry {
  relativePath: string
}

export interface ComposerUploadDraftChange {
  value: string
  selectionStart: number
  selectionEnd: number
}

interface ComposerUploadDraftUpdateInput {
  uploadDraftKey: string | null
  currentDraftKey: string | null
  currentDraft: string
  storedDraft: string
  paths: string[]
  selectionStart?: number
  selectionEnd?: number
  alignmentPromptPrefix?: string
}

export interface ComposerUploadDraftUpdate {
  applyToCurrent: boolean
  draftKey: string | null
  change: ComposerUploadDraftChange
}

interface BooleanRef {
  current: boolean
}

const UPLOAD_BLOCK_HEADER = '已上传：\n'

function normalizePath(path: string) {
  return path.trim().replace(/\\/g, '/')
}

function uniquePaths(paths: string[]) {
  const seen = new Set<string>()
  return paths.filter((path) => {
    const normalized = normalizePath(path)
    if (!normalized || seen.has(normalized)) return false
    seen.add(normalized)
    return true
  }).map(normalizePath)
}

export function collectComposerUploadPaths(
  kind: ComposerUploadKind,
  entries: UploadPathEntry[],
  uploadedFiles: FileInfo[],
) {
  if (kind === 'files') {
    return uniquePaths(uploadedFiles.map((file) => file.path))
  }

  return uniquePaths(entries.map((entry) => {
    const root = normalizePath(entry.relativePath).split('/').find(Boolean)
    return root ? `${root}/` : ''
  }))
}

function parseUploadBlock(draft: string, start: number) {
  if (!draft.startsWith(UPLOAD_BLOCK_HEADER, start)) return null

  const paths: string[] = []
  let cursor = start + UPLOAD_BLOCK_HEADER.length
  while (cursor < draft.length) {
    const newline = draft.indexOf('\n', cursor)
    const lineEnd = newline === -1 ? draft.length : newline
    const line = draft.slice(cursor, lineEnd)
    if (!line.startsWith('- `') || !line.endsWith('`')) break
    paths.push(line.slice(3, -1))
    cursor = newline === -1 ? draft.length : newline + 1
  }

  if (!paths.length) return null
  if (draft.startsWith('\n', cursor)) cursor += 1
  return { paths, end: cursor }
}

function formatUploadBlock(paths: string[]) {
  return `${UPLOAD_BLOCK_HEADER}${paths.map((path) => `- \`${path}\``).join('\n')}\n\n`
}

function clampSelection(value: number, length: number) {
  return Math.max(0, Math.min(value, length))
}

export function mergeComposerUploadPaths(
  draft: string,
  paths: string[],
  selectionStart = draft.length,
  selectionEnd = selectionStart,
  alignmentPromptPrefix = '',
): ComposerUploadDraftChange {
  const incoming = uniquePaths(paths)
  if (!incoming.length) {
    return {
      value: draft,
      selectionStart: clampSelection(selectionStart, draft.length),
      selectionEnd: clampSelection(selectionEnd, draft.length),
    }
  }

  const blockStart = alignmentPromptPrefix && draft.startsWith(alignmentPromptPrefix)
    ? alignmentPromptPrefix.length
    : 0
  const existing = parseUploadBlock(draft, blockStart)
  const existingPaths = existing?.paths || []
  const seen = new Set(existingPaths.map(normalizePath))
  const additions = incoming.filter((path) => {
    const key = normalizePath(path)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  if (existing && !additions.length) {
    return {
      value: draft,
      selectionStart: clampSelection(selectionStart, draft.length),
      selectionEnd: clampSelection(selectionEnd, draft.length),
    }
  }

  const mergedPaths = [...existingPaths, ...additions]
  const oldBlockEnd = existing?.end ?? blockStart
  const block = formatUploadBlock(mergedPaths)
  const value = `${draft.slice(0, blockStart)}${block}${draft.slice(oldBlockEnd)}`
  const delta = block.length - (oldBlockEnd - blockStart)
  const moveSelection = (position: number) => position >= oldBlockEnd ? position + delta : position

  return {
    value,
    selectionStart: clampSelection(moveSelection(selectionStart), value.length),
    selectionEnd: clampSelection(moveSelection(selectionEnd), value.length),
  }
}

export function prepareComposerUploadDraftUpdate({
  uploadDraftKey,
  currentDraftKey,
  currentDraft,
  storedDraft,
  paths,
  selectionStart,
  selectionEnd,
  alignmentPromptPrefix = '',
}: ComposerUploadDraftUpdateInput): ComposerUploadDraftUpdate {
  const applyToCurrent = uploadDraftKey === currentDraftKey
  const targetDraft = applyToCurrent ? currentDraft : storedDraft
  return {
    applyToCurrent,
    draftKey: uploadDraftKey,
    change: mergeComposerUploadPaths(
      targetDraft,
      paths,
      applyToCurrent ? selectionStart : targetDraft.length,
      applyToCurrent ? selectionEnd : targetDraft.length,
      alignmentPromptPrefix,
    ),
  }
}

export function selectComposerUploadTargetDraft(
  applyToCurrent: boolean,
  textareaDraft: string | undefined,
  latestCurrentDraft: string,
  storedDraft: string,
) {
  return applyToCurrent ? textareaDraft ?? latestCurrentDraft : storedDraft
}

export function acquireComposerUploadLock(lock: BooleanRef): (() => void) | null {
  if (lock.current) return null
  lock.current = true
  return () => {
    lock.current = false
  }
}
