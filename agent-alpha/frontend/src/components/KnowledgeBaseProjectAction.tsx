import { BookOpen } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { placeKnowledgeBasePopover, type PopoverPosition } from '../knowledgeBase'
import type { Project } from '../types'

type ConfirmationStage = 'intro' | 'warning' | null

interface KnowledgeBaseProjectActionProps {
  project: Project
  busy: boolean
  onInitialize: (project: Project) => void
}

export default function KnowledgeBaseProjectAction({
  project,
  busy,
  onInitialize,
}: KnowledgeBaseProjectActionProps) {
  const [stage, setStage] = useState<ConfirmationStage>(null)
  const [position, setPosition] = useState<PopoverPosition | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const anchorRef = useRef<HTMLButtonElement | null>(null)
  const popoverRef = useRef<HTMLDivElement | null>(null)

  const close = () => {
    setStage(null)
    setPosition(null)
  }

  useLayoutEffect(() => {
    if (!stage || !anchorRef.current || !popoverRef.current) return
    const updatePosition = () => {
      if (!anchorRef.current || !popoverRef.current) return
      setPosition(placeKnowledgeBasePopover(
        anchorRef.current.getBoundingClientRect(),
        popoverRef.current.offsetHeight,
        window.innerWidth,
        window.innerHeight,
      ))
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [stage])

  useEffect(() => {
    if (stage !== 'intro') return
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close()
    }
    window.addEventListener('pointerdown', handlePointerDown)
    return () => window.removeEventListener('pointerdown', handlePointerDown)
  }, [stage])

  return (
    <div
      ref={rootRef}
      className="knowledge-base-project-action"
      onMouseLeave={stage === 'intro' ? close : undefined}
    >
      <button
        ref={anchorRef}
        className="item-action"
        type="button"
        title="改造为知识库"
        aria-label={`将项目「${project.name}」改造为知识库`}
        aria-expanded={Boolean(stage)}
        disabled={busy}
        onClick={() => {
          if (busy) return
          setPosition(null)
          setStage('intro')
        }}
      >
        <BookOpen size={14} />
      </button>
      {stage && (
        <div
          ref={popoverRef}
          className="knowledge-base-project-popover"
          role="dialog"
          aria-label="改造知识库确认"
          style={{
            left: position?.left ?? 0,
            top: position?.top ?? 0,
            visibility: position ? 'visible' : 'hidden',
          }}
        >
          <p>
            {stage === 'intro'
              ? '升级项目为知识库'
              : '改造知识库会重新整理项目文件结构，但不会修改文档内容。转换完成后不能一键撤销。'}
          </p>
          <div className="knowledge-base-project-popover-actions">
            <button type="button" onClick={close}>否</button>
            <button
              type="button"
              className="primary"
              onClick={() => {
                if (stage === 'intro') {
                  setPosition(null)
                  setStage('warning')
                  return
                }
                close()
                onInitialize(project)
              }}
            >
              是
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
