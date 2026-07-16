import type { PptxViewer as PptxViewerInstance } from '@aiden0z/pptx-renderer'
import { useEffect, useRef, useState } from 'react'

interface PptxPreviewProps {
  name: string
  url: string
}

function errorMessage(error: unknown) {
  if (error instanceof Error && error.message) return error.message
  return String(error)
}

export default function PptxPreview({ name, url }: PptxPreviewProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const slidesRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const scrollContainer = scrollRef.current
    const slidesContainer = slidesRef.current
    if (!scrollContainer || !slidesContainer) return

    const controller = new AbortController()
    let viewer: PptxViewerInstance | null = null

    setLoading(true)
    setError(null)
    slidesContainer.replaceChildren()

    const load = async () => {
      try {
        const [renderer, response] = await Promise.all([
          import('@aiden0z/pptx-renderer'),
          fetch(url, { cache: 'no-store', signal: controller.signal }),
        ])
        if (!response.ok) throw new Error(`读取 PPTX 失败（${response.status}）`)
        const buffer = await response.arrayBuffer()
        if (controller.signal.aborted) return

        viewer = new renderer.PptxViewer(slidesContainer, {
          fitMode: 'contain',
          scrollContainer,
          zipLimits: renderer.RECOMMENDED_ZIP_LIMITS,
          lazySlides: true,
          lazyMedia: true,
          pdfjs: false,
        })
        await viewer.open(buffer, {
          renderMode: 'list',
          signal: controller.signal,
          lazySlides: true,
          lazyMedia: true,
          listOptions: {
            windowed: true,
            initialSlides: 4,
            batchSize: 4,
            overscanViewport: 1.5,
            showSlideLabels: true,
          },
        })
        if (!controller.signal.aborted) setLoading(false)
      } catch (loadError) {
        if (controller.signal.aborted) return
        setLoading(false)
        setError(`无法预览这个 PPTX：${errorMessage(loadError)}`)
      }
    }

    void load()
    return () => {
      controller.abort()
      viewer?.destroy()
    }
  }, [url])

  return (
    <div className="pptx-preview" ref={scrollRef} aria-label={`${name} 幻灯片预览`}>
      {loading && <div className="pptx-preview-status">正在加载 PPT…</div>}
      {error && <div className="pptx-preview-status danger">{error}</div>}
      <div className="pptx-preview-slides" ref={slidesRef} />
    </div>
  )
}
