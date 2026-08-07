import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { ALIGNMENT_PROMPT_PREFIX } from '../src/alignmentPrompt.ts'
import {
  acquireComposerUploadLock,
  collectComposerUploadPaths,
  mergeComposerUploadPaths,
  prepareComposerUploadDraftUpdate,
  selectComposerUploadTargetDraft,
} from '../src/composerUploadPaths.ts'

test('空草稿上传文件时只创建相对路径区块', () => {
  const change = mergeComposerUploadPaths('', ['论文.pdf'], 0, 0)

  assert.equal(change.value, '已上传：\n- `论文.pdf`\n\n')
  assert.equal(change.selectionStart, change.value.length)
  assert.equal(change.selectionEnd, change.value.length)
  assert.doesNotMatch(change.value, /请阅读|请处理/)
})

test('已有多行提示词逐字保留且选区跟随前置区块移动', () => {
  const draft = '翻译成中文。\n  保留这里的空格。'
  const change = mergeComposerUploadPaths(draft, ['资料/论文.pdf'], 2, 8)
  const prefix = '已上传：\n- `资料/论文.pdf`\n\n'

  assert.equal(change.value, `${prefix}${draft}`)
  assert.equal(change.selectionStart, prefix.length + 2)
  assert.equal(change.selectionEnd, prefix.length + 8)
})

test('连续上传合并到同一区块并按首次出现顺序去重', () => {
  const first = mergeComposerUploadPaths('正文', ['论文.pdf', '参考资料/'])
  const second = mergeComposerUploadPaths(first.value, ['论文.pdf', '补充.docx'])

  assert.equal(
    second.value,
    '已上传：\n- `论文.pdf`\n- `参考资料/`\n- `补充.docx`\n\n正文',
  )
  assert.equal(second.value.match(/已上传：/g)?.length, 1)
})

test('开启对齐时上传区块位于对齐提示词之后', () => {
  const draft = `${ALIGNMENT_PROMPT_PREFIX}用户正文`
  const change = mergeComposerUploadPaths(
    draft,
    ['论文.pdf'],
    ALIGNMENT_PROMPT_PREFIX.length + 2,
    draft.length,
    ALIGNMENT_PROMPT_PREFIX,
  )
  const uploadBlock = '已上传：\n- `论文.pdf`\n\n'

  assert.equal(change.value, `${ALIGNMENT_PROMPT_PREFIX}${uploadBlock}用户正文`)
  assert.equal(change.selectionStart, ALIGNMENT_PROMPT_PREFIX.length + uploadBlock.length + 2)
  assert.equal(change.selectionEnd, change.value.length)
})

test('位于对齐提示词中的选区不因后方插入上传区块而移动', () => {
  const draft = `${ALIGNMENT_PROMPT_PREFIX}正文`
  const change = mergeComposerUploadPaths(draft, ['论文.pdf'], 1, 5, ALIGNMENT_PROMPT_PREFIX)

  assert.equal(change.selectionStart, 1)
  assert.equal(change.selectionEnd, 5)
})

test('损坏的上传区块被视为原文且不会被删除', () => {
  const malformed = '已上传：\n这里不是标准路径条目\n原文'
  const change = mergeComposerUploadPaths(malformed, ['新文件.txt'])

  assert.equal(change.value, `已上传：\n- \`新文件.txt\`\n\n${malformed}`)
})

test('文件上传使用后端返回的最终路径', () => {
  const paths = collectComposerUploadPaths(
    'files',
    [{ relativePath: '论文.pdf' }],
    [{ name: '论文（副本）.pdf', path: '论文（副本）.pdf', size: 10, is_dir: false }],
  )

  assert.deepEqual(paths, ['论文（副本）.pdf'])
})

test('文件夹上传只展示根目录并兼容中文空格和多层内容', () => {
  const paths = collectComposerUploadPaths(
    'folder',
    [
      { relativePath: '参考 资料/论文.pdf' },
      { relativePath: '参考 资料/图片/图一.png' },
      { relativePath: '第二批/说明.txt' },
    ],
    [],
  )

  assert.deepEqual(paths, ['参考 资料/', '第二批/'])
})

test('上传公共函数按顺序返回后端最终文件信息', async () => {
  const { api } = await import('../src/api/client.ts')
  const { uploadProjectFiles } = await import('../src/upload.ts')
  const originalUploadFile = api.uploadFile
  const responses = [
    { name: '甲_(1).txt', path: '甲_(1).txt', size: 1, is_dir: false },
    { name: '乙.txt', path: '乙.txt', size: 1, is_dir: false },
  ]
  const relativePaths = []
  const strategies = []
  api.uploadFile = async (formData) => {
    relativePaths.push(formData.get('relative_path'))
    strategies.push(formData.get('conflict_strategy'))
    return responses[relativePaths.length - 1]
  }

  try {
    const files = await uploadProjectFiles(
      'project-a',
      '',
      [
        { file: new Blob(['a']), relativePath: '甲.txt' },
        { file: new Blob(['b']), relativePath: '乙.txt' },
      ],
    )

    assert.deepEqual(relativePaths, ['甲.txt', '乙.txt'])
    assert.deepEqual(strategies, ['rename', 'rename'])
    assert.deepEqual(files, responses)
  } finally {
    api.uploadFile = originalUploadFile
  }
})

test('两个上传入口不再预检查重名或显示处理弹窗', () => {
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const drawerSource = readFileSync(new URL('../src/components/FileDrawer.tsx', import.meta.url), 'utf8')
  const uploadSource = readFileSync(new URL('../src/upload.ts', import.meta.url), 'utf8')
  const clientSource = readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8')
  const typesSource = readFileSync(new URL('../src/types/index.ts', import.meta.url), 'utf8')

  for (const source of [appSource, drawerSource]) {
    assert.doesNotMatch(source, /checkProjectUploadConflicts/)
    assert.doesNotMatch(source, /发现重名|保留两份/)
  }
  assert.match(uploadSource, /formData\.set\('conflict_strategy', 'rename'\)/)
  assert.doesNotMatch(clientSource, /checkFileConflicts/)
  assert.doesNotMatch(typesSource, /interface UploadConflictItem/)
})

test('上传期间切换会话时只准备更新原草稿', () => {
  const update = prepareComposerUploadDraftUpdate({
    uploadDraftKey: 'draft:session-a',
    currentDraftKey: 'draft:session-b',
    currentDraft: '会话 B 正文',
    storedDraft: '会话 A 正文',
    paths: ['论文.pdf'],
    alignmentPromptPrefix: ALIGNMENT_PROMPT_PREFIX,
  })

  assert.equal(update.applyToCurrent, false)
  assert.equal(update.draftKey, 'draft:session-a')
  assert.equal(update.change.value, '已上传：\n- `论文.pdf`\n\n会话 A 正文')
})

test('上传仍在原会话时使用输入框最新值和选区', () => {
  const update = prepareComposerUploadDraftUpdate({
    uploadDraftKey: 'draft:session-a',
    currentDraftKey: 'draft:session-a',
    currentDraft: '上传期间继续输入',
    storedDraft: '旧草稿',
    paths: ['论文.pdf'],
    selectionStart: 2,
    selectionEnd: 4,
    alignmentPromptPrefix: ALIGNMENT_PROMPT_PREFIX,
  })
  const prefix = '已上传：\n- `论文.pdf`\n\n'

  assert.equal(update.applyToCurrent, true)
  assert.equal(update.change.value, `${prefix}上传期间继续输入`)
  assert.equal(update.change.selectionStart, prefix.length + 2)
  assert.equal(update.change.selectionEnd, prefix.length + 4)
})

test('当前草稿输入框已卸载时使用最新草稿状态而不是旧缓存', () => {
  assert.equal(selectComposerUploadTargetDraft(true, undefined, '', '上传前旧草稿'), '')
  assert.equal(selectComposerUploadTargetDraft(true, undefined, '设置页前最新草稿', '上传前旧草稿'), '设置页前最新草稿')
  assert.equal(selectComposerUploadTargetDraft(false, undefined, '当前其他会话', '原会话缓存'), '原会话缓存')
})

test('用户手动修改的已有路径显示保持原样并按规范化路径去重', () => {
  const draft = '已上传：\n- `资料\\论文.pdf`\n\n正文'
  const change = mergeComposerUploadPaths(draft, ['资料/论文.pdf', '补充.txt'])

  assert.equal(change.value, '已上传：\n- `资料\\论文.pdf`\n- `补充.txt`\n\n正文')
})

test('上传批次锁拒绝并发并可在完成后释放', () => {
  const lock = { current: false }
  const release = acquireComposerUploadLock(lock)

  assert.equal(typeof release, 'function')
  assert.equal(lock.current, true)
  assert.equal(acquireComposerUploadLock(lock), null)

  release()
  assert.equal(lock.current, false)
  assert.equal(typeof acquireComposerUploadLock(lock), 'function')
})
