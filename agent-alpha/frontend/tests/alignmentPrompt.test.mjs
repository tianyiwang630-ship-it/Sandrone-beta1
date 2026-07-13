import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ALIGNMENT_PROMPT,
  ALIGNMENT_PROMPT_PREFIX,
  draftAfterSend,
  insertAlignmentPrompt,
  removeUnchangedAlignmentPrompt,
} from '../src/alignmentPrompt.ts'

test('开启对齐会把提示词插到空草稿开头，并把光标放到新行', () => {
  const change = insertAlignmentPrompt('')
  assert.equal(change.value, ALIGNMENT_PROMPT_PREFIX)
  assert.equal(change.selectionStart, ALIGNMENT_PROMPT_PREFIX.length)
  assert.equal(change.selectionEnd, ALIGNMENT_PROMPT_PREFIX.length)
})

test('开启对齐会保留已有正文，并把光标放到正文前的新行开头', () => {
  const change = insertAlignmentPrompt('已有正文')
  assert.equal(change.value, `${ALIGNMENT_PROMPT_PREFIX}已有正文`)
  assert.equal(change.selectionStart, ALIGNMENT_PROMPT_PREFIX.length)
  assert.equal(change.selectionEnd, ALIGNMENT_PROMPT_PREFIX.length)
})

test('开启时不检查已有提示词，因此重复开启会再次插入', () => {
  const first = insertAlignmentPrompt('正文')
  const second = insertAlignmentPrompt(first.value)
  assert.equal(second.value, `${ALIGNMENT_PROMPT_PREFIX}${ALIGNMENT_PROMPT_PREFIX}正文`)
})

test('发送后仍开启对齐时会恢复提示词和新行', () => {
  assert.equal(draftAfterSend(true), ALIGNMENT_PROMPT_PREFIX)
})

test('发送后已经关闭对齐时会恢复为空草稿', () => {
  assert.equal(draftAfterSend(false), '')
})

test('关闭会删除开头完全未改的提示词和生成的换行', () => {
  const draft = `${ALIGNMENT_PROMPT_PREFIX}正文`
  const change = removeUnchangedAlignmentPrompt(draft, ALIGNMENT_PROMPT_PREFIX.length + 2, draft.length)
  assert.equal(change.value, '正文')
  assert.equal(change.selectionStart, 2)
  assert.equal(change.selectionEnd, 2)
  assert.equal(change.removed, true)
})

test('关闭会删除输入框中唯一且完整的提示词', () => {
  const change = removeUnchangedAlignmentPrompt(ALIGNMENT_PROMPT, ALIGNMENT_PROMPT.length, ALIGNMENT_PROMPT.length)
  assert.equal(change.value, '')
  assert.equal(change.selectionStart, 0)
  assert.equal(change.selectionEnd, 0)
  assert.equal(change.removed, true)
})

test('提示词内的光标在删除后落到正文开头', () => {
  const change = removeUnchangedAlignmentPrompt(`${ALIGNMENT_PROMPT_PREFIX}正文`, 3, 8)
  assert.equal(change.value, '正文')
  assert.equal(change.selectionStart, 0)
  assert.equal(change.selectionEnd, 0)
})

test('提示词后有多个换行时只删除自动生成的第一个换行', () => {
  const change = removeUnchangedAlignmentPrompt(`${ALIGNMENT_PROMPT_PREFIX}\n正文`, ALIGNMENT_PROMPT_PREFIX.length, ALIGNMENT_PROMPT_PREFIX.length)
  assert.equal(change.value, '\n正文')
  assert.equal(change.selectionStart, 0)
  assert.equal(change.selectionEnd, 0)
})

test('提示词任何字符被修改时关闭只切换状态，不改草稿和选区', () => {
  const draft = `请${ALIGNMENT_PROMPT.slice(1)}\n正文`
  const change = removeUnchangedAlignmentPrompt(draft, 4, 7)
  assert.equal(change.value, draft)
  assert.equal(change.selectionStart, 4)
  assert.equal(change.selectionEnd, 7)
  assert.equal(change.removed, false)
})

test('提示词不在绝对开头时不会删除', () => {
  const draft = ` ${ALIGNMENT_PROMPT_PREFIX}正文`
  const change = removeUnchangedAlignmentPrompt(draft, draft.length, draft.length)
  assert.equal(change.value, draft)
  assert.equal(change.removed, false)
})

test('提示词后直接追加字符而没有生成的换行时不会删除', () => {
  const draft = `${ALIGNMENT_PROMPT}补充`
  const change = removeUnchangedAlignmentPrompt(draft, draft.length, draft.length)
  assert.equal(change.value, draft)
  assert.equal(change.removed, false)
})

test('未删除时会把越界选区收束到草稿范围', () => {
  const change = removeUnchangedAlignmentPrompt('正文', -5, 99)
  assert.equal(change.selectionStart, 0)
  assert.equal(change.selectionEnd, 2)
})
