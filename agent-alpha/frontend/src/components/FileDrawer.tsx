import {
  ChevronLeft,
  Eye,
  ExternalLink,
  FilePlus2,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  RefreshCw,
  Upload,
  X,
} from 'lucide-react'
import { ChangeEvent, MouseEvent, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { FileContent, FileInfo, Project, UploadConflictItem } from '../types'
import {
  buildFolderFiles,
  checkProjectUploadConflicts,
  uploadProjectFiles,
  type ConflictStrategy,
  type UploadEntry,
} from '../upload'

interface FileDrawerProps {
  project: Project | null
  open: boolean
  onClose: () => void
  width: number
  onResizeStart: (event: MouseEvent<HTMLButtonElement>) => void
  refreshKey?: number
}

const MIN_FILE_LIST_WIDTH = 70
const MIN_PREVIEW_WIDTH = 80

function parentPath(path: string) {
  const parts = path.split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
}

function formatSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function escapeHtmlAttribute(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(value: string) {
  return escapeHtml(value)
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match, label, href) => {
      const safeHref = /^(https?:|mailto:|#)/i.test(href) ? href : '#'
      return `<a href="${escapeHtmlAttribute(safeHref)}" target="_blank" rel="noreferrer">${label}</a>`
    })
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isTableSeparator(line: string) {
  const cells = splitTableRow(line)
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function renderMarkdownTable(lines: string[], start: number) {
  const header = splitTableRow(lines[start] || '')
  const body: string[][] = []
  let index = start + 2

  while (index < lines.length && (lines[index] || '').includes('|') && (lines[index] || '').trim()) {
    body.push(splitTableRow(lines[index] || ''))
    index += 1
  }

  const thead = `<thead><tr>${header.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join('')}</tr></thead>`
  const tbody = body.length
    ? `<tbody>${body
        .map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`)
        .join('')}</tbody>`
    : ''

  return {
    html: `<table>${thead}${tbody}</table>`,
    nextIndex: index,
  }
}

function renderMarkdownPreview(content: string) {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const blocks: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] || ''
    const trimmed = line.trim()
    if (!trimmed) {
      index += 1
      continue
    }

    const fence = trimmed.match(/^```([\w-]+)?\s*$/)
    if (fence) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !(lines[index] || '').trim().startsWith('```')) {
        codeLines.push(lines[index] || '')
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
      continue
    }

    if (/^\|?.+\|.+$/.test(trimmed) && index + 1 < lines.length && isTableSeparator(lines[index + 1] || '')) {
      const table = renderMarkdownTable(lines, index)
      blocks.push(table.html)
      index = table.nextIndex
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      index += 1
      continue
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index] || '')) {
        items.push(`<li>${renderInlineMarkdown((lines[index] || '').replace(/^\s*[-*+]\s+/, ''))}</li>`)
        index += 1
      }
      blocks.push(`<ul>${items.join('')}</ul>`)
      continue
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index] || '')) {
        items.push(`<li>${renderInlineMarkdown((lines[index] || '').replace(/^\s*\d+\.\s+/, ''))}</li>`)
        index += 1
      }
      blocks.push(`<ol>${items.join('')}</ol>`)
      continue
    }

    const paragraphLines: string[] = []
    while (index < lines.length) {
      const current = lines[index] || ''
      const currentTrimmed = current.trim()
      if (!currentTrimmed) break
      if (
        /^```/.test(currentTrimmed) ||
        /^(#{1,6})\s+/.test(current) ||
        /^\s*[-*+]\s+/.test(current) ||
        /^\s*\d+\.\s+/.test(current) ||
        (/^\|?.+\|.+$/.test(currentTrimmed) && index + 1 < lines.length && isTableSeparator(lines[index + 1] || ''))
      ) {
        break
      }
      paragraphLines.push(currentTrimmed)
      index += 1
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraphLines.join(' '))}</p>`)
  }

  return blocks.join('')
}

function buildHtmlPreview(content: string, baseHref: string) {
  const baseTag = `<base href="${escapeHtmlAttribute(baseHref)}">`
  if (/<head(\s|>)/i.test(content)) {
    return content.replace(/<head(\s*)>/i, (match) => `${match}${baseTag}`)
  }
  if (/<html(\s|>)/i.test(content)) {
    return content.replace(/<html(\s*)>/i, (match) => `${match}<head>${baseTag}</head>`)
  }
  return `<!doctype html><html><head>${baseTag}</head><body>${content}</body></html>`
}

function toNativeRelativePath(relativePath: string, workspacePath: string) {
  const separator = workspacePath.includes('\\') ? '\\' : '/'
  return relativePath.replace(/\//g, separator)
}

function toAbsoluteWorkspacePath(workspacePath: string, relativePath: string) {
  const separator = workspacePath.includes('\\') ? '\\' : '/'
  const normalizedRoot = workspacePath.replace(/[\\/]+$/, '')
  if (!relativePath) return normalizedRoot
  return `${normalizedRoot}${separator}${toNativeRelativePath(relativePath, workspacePath)}`
}

function isMarkdownFile(file: FileContent | null) {
  if (!file || !file.previewable || !file.content) return false
  return file.language === 'markdown' || /\.(md|markdown)$/i.test(file.name)
}

export default function FileDrawer({ project, open, onClose, width, onResizeStart, refreshKey = 0 }: FileDrawerProps) {
  const [path, setPath] = useState('')
  const [items, setItems] = useState<FileInfo[]>([])
  const [selected, setSelected] = useState<FileContent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [contextItem, setContextItem] = useState<FileInfo | null>(null)
  const [contextPos, setContextPos] = useState({ x: 0, y: 0 })
  const [targetUploadPath, setTargetUploadPath] = useState('')
  const [conflicts, setConflicts] = useState<UploadConflictItem[]>([])
  const [pendingUpload, setPendingUpload] = useState<UploadEntry[] | null>(null)
  const [showConflictDialog, setShowConflictDialog] = useState(false)
  const [fileListWidth, setFileListWidth] = useState(320)
  const [renderMarkdown, setRenderMarkdown] = useState(false)
  const [draggingInternalSplit, setDraggingInternalSplit] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const splitDragRef = useRef({ x: 0, fileListWidth: 320 })

  const maxFileListWidth = Math.max(MIN_FILE_LIST_WIDTH, width - MIN_PREVIEW_WIDTH)
  const canRenderMarkdown = isMarkdownFile(selected)

  const load = async (nextPath = path) => {
    if (!project) return
    setLoading(true)
    setError(null)
    try {
      const data = await api.listFiles(project.id, nextPath || undefined)
      setItems(data.items)
      setPath(data.path)
      if (selected?.path && selected.path.startsWith(data.path)) {
        // Keep selection visible where possible.
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && project) {
      setPath('')
      setSelected(null)
      setContextItem(null)
      void load('')
    }
  }, [open, project?.id])

  useEffect(() => {
    if (open && project) {
      void load(path)
    }
  }, [refreshKey])

  useEffect(() => {
    if (!open) return
    const closeMenu = () => setContextItem(null)
    window.addEventListener('click', closeMenu)
    return () => window.removeEventListener('click', closeMenu)
  }, [open])

  useEffect(() => {
    setFileListWidth((current) => Math.min(current, maxFileListWidth))
  }, [maxFileListWidth])

  useEffect(() => {
    if (!draggingInternalSplit) return

    const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

    const handleMouseMove = (event: globalThis.MouseEvent) => {
      const deltaX = splitDragRef.current.x - event.clientX
      setFileListWidth(clamp(splitDragRef.current.fileListWidth + deltaX, MIN_FILE_LIST_WIDTH, maxFileListWidth))
    }

    const handleMouseUp = () => setDraggingInternalSplit(false)

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [draggingInternalSplit, maxFileListWidth])

  const openItem = async (item: FileInfo) => {
    if (!project) return
    if (item.is_dir) {
      setSelected(null)
      setRenderMarkdown(false)
      await load(item.path)
      return
    }
    setError(null)
    try {
      setSelected(await api.readFile(project.id, item.path))
      setRenderMarkdown(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const uploadBatch = async (
    files: UploadEntry[],
    strategy?: ConflictStrategy,
    explicitTargetPath?: string,
  ) => {
    if (!project || !files.length) return
    const targetPath = explicitTargetPath ?? targetUploadPath ?? path
    setUploading(true)
    setError(null)
    try {
      await uploadProjectFiles(project.id, targetPath, files, strategy)
      setPendingUpload(null)
      setShowConflictDialog(false)
      setTargetUploadPath('')
      await load(targetPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploading(false)
    }
  }

  const handlePickedFiles = async (entries: UploadEntry[], target = path) => {
    if (!project || !entries.length) return
    setTargetUploadPath(target)
    try {
      const conflictData = await checkProjectUploadConflicts(project.id, target, entries)
      if (conflictData.has_conflicts) {
        setPendingUpload(entries)
        setConflicts(conflictData.conflicts)
        setShowConflictDialog(true)
        return
      }
      await uploadBatch(entries, undefined, target)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const handleFileSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []).map((file) => ({ file, relativePath: file.name }))
    await handlePickedFiles(files, targetUploadPath || path)
    event.target.value = ''
  }

  const handleFolderSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = buildFolderFiles(event.target.files)
    await handlePickedFiles(files, targetUploadPath || path)
    event.target.value = ''
  }

  const openContextMenu = (event: MouseEvent<HTMLButtonElement>, item: FileInfo) => {
    event.preventDefault()
    event.stopPropagation()
    setContextItem(item)
    setContextPos({ x: event.clientX, y: event.clientY })
  }

  const openInExplorer = async (item: FileInfo) => {
    if (!project) return
    setContextItem(null)
    try {
      await api.openInFolder({ project_id: project.id, path: item.path })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const copyPath = async (kind: 'absolute' | 'relative', item: FileInfo) => {
    if (!project) return
    setContextItem(null)
    const value =
      kind === 'absolute'
        ? toAbsoluteWorkspacePath(project.workspace_path, item.path)
        : toNativeRelativePath(item.path, project.workspace_path)
    try {
      await navigator.clipboard.writeText(value)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const openWorkspaceRoot = async () => {
    if (!project) return
    try {
      await api.openInFolder({ project_id: project.id, path: '' })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const uploadToDirectory = (directory: FileInfo, kind: 'file' | 'folder') => {
    setTargetUploadPath(directory.path)
    setContextItem(null)
    if (kind === 'file') fileInputRef.current?.click()
    else folderInputRef.current?.click()
  }

  const createFolder = async () => {
    if (!project) return
    const name = window.prompt('新文件夹名称')
    if (!name?.trim()) return
    try {
      await api.createFolder({ project_id: project.id, target_path: path, name: name.trim() })
      await load(path)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const startInternalResize = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    splitDragRef.current = { x: event.clientX, fileListWidth }
    setDraggingInternalSplit(true)
  }

  if (!open) return null

  return (
    <aside className={`file-drawer ${draggingInternalSplit ? 'is-splitting' : ''}`} style={{ width }}>
      <button
        type="button"
        className="drawer-resizer"
        title="拖动调整文件区宽度"
        aria-label="拖动调整文件区宽度"
        onMouseDown={onResizeStart}
      />
      <header className="drawer-header">
        <div>
          <p className="eyebrow">文件</p>
          <h2>{project?.name || '未选择项目'}</h2>
        </div>
        <div className="icon-row">
          <button
            title="上传文件到当前目录"
            className="icon-button"
            onClick={() => {
              setTargetUploadPath(path)
              fileInputRef.current?.click()
            }}
          >
            <Upload size={17} />
          </button>
          <button
            title="上传文件夹到当前目录"
            className="icon-button"
            onClick={() => {
              setTargetUploadPath(path)
              folderInputRef.current?.click()
            }}
          >
            <FolderPlus size={17} />
          </button>
          <button title="新建文件夹" className="icon-button" onClick={() => void createFolder()}>
            <FilePlus2 size={17} />
          </button>
          <button title="打开整个工作区" className="icon-button" onClick={() => void openWorkspaceRoot()}>
            <ExternalLink size={17} />
          </button>
          <button title="刷新" className="icon-button" onClick={() => void load()}>
            <RefreshCw size={17} />
          </button>
          <button title="关闭" className="icon-button" onClick={onClose}>
            <X size={17} />
          </button>
        </div>
      </header>

      <input ref={fileInputRef} type="file" multiple hidden onChange={(event) => void handleFileSelect(event)} />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        hidden
        {...({ directory: '', webkitdirectory: '' } as Record<string, string>)}
        onChange={(event) => void handleFolderSelect(event)}
      />

      <div className="drawer-body">
        <div className="file-toolbar">
          <button
            title="上一层"
            className="icon-button"
            disabled={!path}
            onClick={() => void load(parentPath(path))}
          >
            <ChevronLeft size={17} />
          </button>
          <span className="path-label">{path || project?.workspace_path || ''}</span>
          <span className="toolbar-hint">{uploading ? '上传中…' : '上传只会进入当前项目工作区'}</span>
        </div>

        {error && <div className="notice danger">{error}</div>}
        {loading && <div className="notice">加载中…</div>}

        <div
          className="file-grid"
          style={{ gridTemplateColumns: `minmax(0, 1fr) 8px minmax(${MIN_FILE_LIST_WIDTH}px, ${fileListWidth}px)` }}
        >
          <div className="preview-pane">
            {selected ? (
              <>
                <div className="preview-title">
                  <FileText size={16} />
                  <span>{selected.name}</span>
                  <small>{formatSize(selected.size)}</small>
                  {canRenderMarkdown && (
                    <button
                      type="button"
                      className={`preview-title-action ${renderMarkdown ? 'active' : ''}`}
                      title={renderMarkdown ? '取消渲染 Markdown' : '渲染 Markdown'}
                      onClick={() => setRenderMarkdown((value) => !value)}
                    >
                      <Eye size={15} />
                    </button>
                  )}
                </div>
                {selected.previewable && selected.language === 'pdf' && project ? (
                  <iframe
                    className="file-preview-frame"
                    title={selected.name}
                    src={api.rawFileUrl(project.id, selected.path)}
                  />
                ) : selected.previewable && selected.language === 'html' && project && selected.content ? (
                  <iframe
                    className="file-preview-frame"
                    title={selected.name}
                    sandbox=""
                    srcDoc={buildHtmlPreview(selected.content, api.assetBaseUrl(project.id, selected.path))}
                  />
                ) : selected.previewable && canRenderMarkdown && renderMarkdown && selected.content ? (
                  <div
                    className="markdown-preview"
                    dangerouslySetInnerHTML={{ __html: renderMarkdownPreview(selected.content) }}
                  />
                ) : selected.previewable ? (
                  <pre>{selected.content}</pre>
                ) : (
                  <div className="empty">{selected.message || '暂不支持预览'}</div>
                )}
              </>
            ) : (
              <div className="empty large">
                <FolderOpen size={30} />
                <span>左侧查看预览，右侧浏览目录</span>
              </div>
            )}
          </div>

          <button
            type="button"
            className="drawer-split-resizer"
            title="拖动调整预览与目录宽度"
            aria-label="拖动调整预览与目录宽度"
            onMouseDown={startInternalResize}
          />

          <div className="file-list">
            {items.map((item) => (
              <button
                key={item.path}
                className={`file-row ${selected?.path === item.path ? 'active' : ''}`}
                onClick={() => void openItem(item)}
                onContextMenu={(event) => openContextMenu(event, item)}
              >
                {item.is_dir ? <Folder size={16} /> : <FileText size={16} />}
                <span>{item.name}</span>
                <small>{item.is_dir ? '' : formatSize(item.size)}</small>
              </button>
            ))}
            {!items.length && !loading && <div className="empty">空目录</div>}
          </div>
        </div>
      </div>

      {contextItem && (
        <div className="file-context-menu" style={{ left: contextPos.x, top: contextPos.y }}>
          {contextItem.is_dir && (
            <>
              <button onClick={() => uploadToDirectory(contextItem, 'file')}>上传文件到这里</button>
              <button onClick={() => uploadToDirectory(contextItem, 'folder')}>上传文件夹到这里</button>
            </>
          )}
          <button onClick={() => void openInExplorer(contextItem)}>在文件夹中打开</button>
          <button onClick={() => void copyPath('absolute', contextItem)}>复制绝对路径</button>
          <button onClick={() => void copyPath('relative', contextItem)}>复制相对路径</button>
        </div>
      )}

      {showConflictDialog && (
        <div className="modal-backdrop">
          <div className="modal-panel">
            <h3>发现重名</h3>
            <p>目标目录里已经有同名文件或文件夹。请选择处理方式。</p>
            <div className="conflict-list">
              {conflicts.slice(0, 6).map((item) => (
                <div key={item.path}>{item.name}</div>
              ))}
              {conflicts.length > 6 && <div>还有更多…</div>}
            </div>
            <div className="modal-actions">
              <button
                className="secondary"
                onClick={() => {
                  setShowConflictDialog(false)
                  setPendingUpload(null)
                }}
              >
                取消
              </button>
              <button
                className="secondary"
                onClick={() => pendingUpload && void uploadBatch(pendingUpload, 'rename')}
              >
                保留两份
              </button>
              <button onClick={() => pendingUpload && void uploadBatch(pendingUpload, 'replace')}>覆盖</button>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
