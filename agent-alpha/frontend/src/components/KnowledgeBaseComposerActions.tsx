import { BookOpen, Minus } from 'lucide-react'
import { useState } from 'react'

interface KnowledgeBaseComposerActionsProps {
  onAdd: () => void
  onRemove: () => void
  onMaintain: () => void
}

export default function KnowledgeBaseComposerActions({
  onAdd,
  onRemove,
  onMaintain,
}: KnowledgeBaseComposerActionsProps) {
  const [expanded, setExpanded] = useState(false)

  if (!expanded) {
    return (
      <button
        className="composer-knowledge-base-button"
        type="button"
        title="维护知识库：增加、移除、全局整理"
        aria-label="维护知识库"
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => setExpanded(true)}
      >
        <BookOpen size={17} />
      </button>
    )
  }

  return (
    <div className="knowledge-base-maintenance" aria-label="知识库维护操作">
      <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={onAdd}>增加</button>
      <button
        type="button"
        title="归档资料，不物理删除"
        onMouseDown={(event) => event.preventDefault()}
        onClick={onRemove}
      >
        移除
      </button>
      <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={onMaintain}>全局整理</button>
      <button
        className="knowledge-base-maintenance-collapse"
        type="button"
        title="收起"
        aria-label="收起知识库维护操作"
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => setExpanded(false)}
      >
        <Minus size={15} />
      </button>
    </div>
  )
}
