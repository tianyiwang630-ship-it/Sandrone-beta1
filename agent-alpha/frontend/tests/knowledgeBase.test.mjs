import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ADD_KNOWLEDGE_BASE_PROMPT,
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

test('新增提示词只盘点新资料并等待确认', () => {
  assert.equal(
    ADD_KNOWLEDGE_BASE_PROMPT,
    '请使用 managing-knowledge-wikis Skill 的“新增资料”模式，检查当前项目中是否存在尚未加入知识库的新文档。请对照 raw/、wiki/index.md、inbox/ 和项目中的其他文件，只做盘点，不要移动文件或修改 Wiki。列出发现的新资料、可能的重复资料、建议加入或暂不加入的内容，等待我确认后再执行。如果没有发现新文档，请提醒我先上传或下载资料。',
  )
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
