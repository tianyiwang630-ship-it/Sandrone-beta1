import type { Project } from './types'

export const INITIALIZE_KNOWLEDGE_BASE_PROMPT =
  '请使用 managing-knowledge-wikis Skill，将当前项目初始化为知识库。请先完整读取 Skill，自行判断当前项目属于“初始化空项目”还是“转换已有项目”。本轮先只读盘点项目文件，给出建议入库内容、暂不入库内容、资料关系和最小 Wiki 结构预览，不要修改或移动任何文件，等待我确认后再继续。'

export const ADD_KNOWLEDGE_BASE_PROMPT =
  '请使用 managing-knowledge-wikis Skill 的“新增资料”模式，检查当前项目中是否存在尚未加入知识库的新文档。请对照 raw/、wiki/index.md、inbox/ 和项目中的其他文件，只做盘点，不要移动文件或修改 Wiki。列出发现的新资料、可能的重复资料、建议加入或暂不加入的内容，等待我确认后再执行。如果没有发现新文档，请提醒我先上传或下载资料。'

export const MAINTAIN_KNOWLEDGE_BASE_PROMPT =
  '请使用 managing-knowledge-wikis Skill 的“全库整理”模式，检查并维护当前知识库。请检查失效链接、重复或孤立页面、分类是否过细、暂未归类资料、缺失关联、来源可信度、相互矛盾的内容，以及归档资料是否仍残留在活跃 Wiki 中。低风险问题可以直接修复；涉及一级分类变化、大量页面移动或多个综合页拆分合并时，先给出调整预览并等待我确认。不要修改 raw/ 中的原始文档，完成后更新索引和日志。'

export const REMOVE_KNOWLEDGE_BASE_DRAFT = '我要从知识库移除以下资料：'

export interface DraftInsertion {
  value: string
  selectionStart: number
  selectionEnd: number
}

export interface PopoverAnchor {
  left: number
  right: number
  top: number
  bottom: number
}

export interface PopoverPosition {
  left: number
  top: number
}

export function placeKnowledgeBasePopover(
  anchor: PopoverAnchor,
  height: number,
  viewportWidth: number,
  viewportHeight: number,
  width = 260,
): PopoverPosition {
  const gap = 6
  const margin = 12
  const maxLeft = Math.max(margin, viewportWidth - width - margin)
  const left = Math.min(Math.max(margin, anchor.right - width), maxLeft)
  const below = anchor.bottom + gap
  const top = below + height <= viewportHeight - margin
    ? below
    : Math.max(margin, anchor.top - height - gap)
  return { left, top }
}

export function insertKnowledgeBaseRemovalDraft(
  draft: string,
  selectionStart?: number | null,
  _selectionEnd?: number | null,
): DraftInsertion {
  const position =
    typeof selectionStart === 'number' && selectionStart >= 0 && selectionStart <= draft.length
      ? selectionStart
      : draft.length
  const cursor = position + REMOVE_KNOWLEDGE_BASE_DRAFT.length
  return {
    value: `${draft.slice(0, position)}${REMOVE_KNOWLEDGE_BASE_DRAFT}${draft.slice(position)}`,
    selectionStart: cursor,
    selectionEnd: cursor,
  }
}

export function replaceProjectById(projects: Project[], replacement: Project): Project[] {
  const index = projects.findIndex((project) => project.id === replacement.id)
  if (index < 0) return projects
  return projects.map((project, projectIndex) => (projectIndex === index ? replacement : project))
}
