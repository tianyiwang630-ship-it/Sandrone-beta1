import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  INITIALIZE_KNOWLEDGE_BASE_PROMPT,
  MAINTAIN_KNOWLEDGE_BASE_PROMPT,
  REMOVE_KNOWLEDGE_BASE_DRAFT,
  insertKnowledgeBaseRemovalDraft,
  placeKnowledgeBasePopover,
  replaceProjectById,
} from '../src/knowledgeBase.ts'

test('初始化提示词要求先盘点、等待确认，不直接改文件', () => {
  assert.equal(
    INITIALIZE_KNOWLEDGE_BASE_PROMPT,
    '请使用 managing-knowledge-wikis Skill，将当前项目初始化为知识库。请先完整读取 Skill，自行判断当前项目属于“初始化空项目”还是“转换已有项目”。本轮先只读盘点项目文件，给出建议入库内容、暂不入库内容、资料关系和最小 Wiki 结构预览，不要修改或移动任何文件，等待我确认后再继续。',
  )
})

test('增加按钮使用可编辑草稿且不点名 Skill', async () => {
  const knowledgeBase = await import('../src/knowledgeBase.ts')
  assert.equal(
    knowledgeBase.ADD_KNOWLEDGE_BASE_DRAFT,
    '请加入知识库：\n未指定文件时，请检查尚未入库的新知识文档并询问我；忽略代码、配置、日志和临时文件。',
  )
  assert.equal(knowledgeBase.ADD_KNOWLEDGE_BASE_PROMPT, undefined)
  assert.doesNotMatch(knowledgeBase.ADD_KNOWLEDGE_BASE_DRAFT, /Skill|managing-knowledge-wikis/i)
})

test('增加草稿插入空文本并把光标停在第一行冒号后', async () => {
  const knowledgeBase = await import('../src/knowledgeBase.ts')
  assert.equal(typeof knowledgeBase.insertKnowledgeBaseAdditionDraft, 'function')
  const change = knowledgeBase.insertKnowledgeBaseAdditionDraft('', 0, 0)
  assert.equal(change.value, knowledgeBase.ADD_KNOWLEDGE_BASE_DRAFT)
  assert.equal(change.selectionStart, '请加入知识库：'.length)
  assert.equal(change.selectionEnd, '请加入知识库：'.length)
})

test('增加草稿在当前光标插入且不覆盖选区', async () => {
  const knowledgeBase = await import('../src/knowledgeBase.ts')
  assert.equal(typeof knowledgeBase.insertKnowledgeBaseAdditionDraft, 'function')
  const change = knowledgeBase.insertKnowledgeBaseAdditionDraft('甲乙丙', 1, 2)
  assert.equal(change.value, `甲${knowledgeBase.ADD_KNOWLEDGE_BASE_DRAFT}乙丙`)
  assert.equal(change.selectionStart, 1 + '请加入知识库：'.length)
  assert.equal(change.selectionEnd, 1 + '请加入知识库：'.length)
})

test('增加草稿无法取得有效光标时追加到末尾', async () => {
  const knowledgeBase = await import('../src/knowledgeBase.ts')
  assert.equal(typeof knowledgeBase.insertKnowledgeBaseAdditionDraft, 'function')
  for (const position of [undefined, -1, 99]) {
    const change = knowledgeBase.insertKnowledgeBaseAdditionDraft('已有草稿', position, position)
    assert.equal(change.value, `已有草稿${knowledgeBase.ADD_KNOWLEDGE_BASE_DRAFT}`)
    assert.equal(change.selectionStart, '已有草稿'.length + '请加入知识库：'.length)
  }
})

test('增加入口只插入草稿，不走自动消息发送', () => {
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(appSource, /onAdd=\{insertKnowledgeBaseAddition\}/)
  assert.doesNotMatch(appSource, /onAdd=\{\(\) => void sendKnowledgeBasePrompt\(ADD_KNOWLEDGE_BASE_PROMPT\)\}/)
})

test('全局整理提示词允许低风险修复，但重大结构变化先确认', () => {
  assert.equal(
    MAINTAIN_KNOWLEDGE_BASE_PROMPT,
    '请使用 managing-knowledge-wikis Skill 的“全库整理”模式，检查并维护当前知识库。请检查失效链接、重复或孤立页面、分类是否过细、暂未归类资料、缺失关联、来源可信度、相互矛盾的内容，以及归档资料是否仍残留在活跃 Wiki 中。低风险问题可以直接修复；涉及一级分类变化、大量页面移动或多个综合页拆分合并时，先给出调整预览并等待我确认。不要修改 raw/ 中的原始文档，完成后更新索引和日志。',
  )
})

test('移除草稿插入空文本并把光标放到文案之后', () => {
  const change = insertKnowledgeBaseRemovalDraft('', 0, 0)
  assert.equal(change.value, REMOVE_KNOWLEDGE_BASE_DRAFT)
  assert.equal(change.selectionStart, REMOVE_KNOWLEDGE_BASE_DRAFT.length)
  assert.equal(change.selectionEnd, REMOVE_KNOWLEDGE_BASE_DRAFT.length)
})

test('移除草稿在当前光标插入，不覆盖选区内容', () => {
  const change = insertKnowledgeBaseRemovalDraft('甲乙丙', 1, 2)
  assert.equal(change.value, `甲${REMOVE_KNOWLEDGE_BASE_DRAFT}乙丙`)
  assert.equal(change.selectionStart, 1 + REMOVE_KNOWLEDGE_BASE_DRAFT.length)
  assert.equal(change.selectionEnd, 1 + REMOVE_KNOWLEDGE_BASE_DRAFT.length)
})

test('无法取得有效光标时追加到末尾', () => {
  for (const position of [undefined, -1, 99]) {
    const change = insertKnowledgeBaseRemovalDraft('已有草稿', position, position)
    assert.equal(change.value, `已有草稿${REMOVE_KNOWLEDGE_BASE_DRAFT}`)
  }
})

test('单项目状态合并保持排序和其他项目对象引用', () => {
  const first = { id: 'p1', name: '一', is_knowledge_base: false }
  const second = { id: 'p2', name: '二', is_knowledge_base: false }
  const projects = [first, second]
  const replacement = { ...second, is_knowledge_base: true }

  const result = replaceProjectById(projects, replacement)

  assert.deepEqual(result.map((project) => project.id), ['p1', 'p2'])
  assert.equal(result[0], first)
  assert.equal(result[1], replacement)
})

test('项目不存在时不创建幽灵条目并复用原数组', () => {
  const projects = [{ id: 'p1', name: '一', is_knowledge_base: false }]
  const result = replaceProjectById(projects, { id: 'missing', name: '无', is_knowledge_base: true })
  assert.equal(result, projects)
})

test('确认框在侧栏底部时翻到按钮上方，并限制在窗口内', () => {
  const position = placeKnowledgeBasePopover(
    { left: 280, right: 308, top: 670, bottom: 698 },
    116,
    320,
    720,
  )
  assert.deepEqual(position, { left: 48, top: 548 })
})

test('确认框在顶部和窄窗口中仍保留安全边距', () => {
  const position = placeKnowledgeBasePopover(
    { left: 0, right: 20, top: 2, bottom: 30 },
    80,
    240,
    100,
  )
  assert.deepEqual(position, { left: 12, top: 12 })
})
