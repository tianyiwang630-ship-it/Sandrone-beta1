export const ALIGNMENT_PROMPT = '请结合全部对话，完整复述你对需求的最新整体理解，并合并我本轮的补充或修改，不要只回应变化的部分。在我明确说“开始实施”之前，不要执行或修改任何内容。'
export const ALIGNMENT_PROMPT_PREFIX = `${ALIGNMENT_PROMPT}\n`

export interface AlignmentDraftChange {
  value: string
  selectionStart: number
  selectionEnd: number
  removed: boolean
}

function clampSelection(value: number, length: number) {
  return Math.max(0, Math.min(value, length))
}

export function insertAlignmentPrompt(draft: string): AlignmentDraftChange {
  const cursor = ALIGNMENT_PROMPT_PREFIX.length
  return {
    value: `${ALIGNMENT_PROMPT_PREFIX}${draft}`,
    selectionStart: cursor,
    selectionEnd: cursor,
    removed: false,
  }
}

export function draftAfterSend(alignmentEnabled: boolean) {
  return alignmentEnabled ? ALIGNMENT_PROMPT_PREFIX : ''
}

export function removeUnchangedAlignmentPrompt(
  draft: string,
  selectionStart: number,
  selectionEnd: number,
): AlignmentDraftChange {
  let removedLength = 0
  if (draft === ALIGNMENT_PROMPT) {
    removedLength = ALIGNMENT_PROMPT.length
  } else if (draft.startsWith(ALIGNMENT_PROMPT_PREFIX)) {
    removedLength = ALIGNMENT_PROMPT_PREFIX.length
  }

  if (!removedLength) {
    return {
      value: draft,
      selectionStart: clampSelection(selectionStart, draft.length),
      selectionEnd: clampSelection(selectionEnd, draft.length),
      removed: false,
    }
  }

  const value = draft.slice(removedLength)
  return {
    value,
    selectionStart: clampSelection(selectionStart - removedLength, value.length),
    selectionEnd: clampSelection(selectionEnd - removedLength, value.length),
    removed: true,
  }
}
