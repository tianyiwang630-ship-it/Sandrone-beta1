import { useEffect, useState } from 'react'
import { api, type MemoryConfig, type MemoryDocument, type MemoryTask, type MemoryVersion } from '../api/client'

type Target = 'user' | 'memory'
type Edit = { id: string; revision: string } | null

export default function MemoryManagement() {
  const [open, setOpen] = useState(false)
  const [config, setConfig] = useState<MemoryConfig | null>(null)
  const [autoPrompt, setAutoPrompt] = useState('')
  const [manualPrompt, setManualPrompt] = useState('')
  const [target, setTarget] = useState<Target>('user')
  const [document, setDocument] = useState<MemoryDocument | null>(null)
  const [draft, setDraft] = useState('')
  const [edit, setEdit] = useState<Edit>(null)
  const [versions, setVersions] = useState<MemoryVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<{ id: string; content: string } | null>(null)
  const [task, setTask] = useState<MemoryTask | null>(null)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [updateDocuments, setUpdateDocuments] = useState(true)
  const [updateReferences, setUpdateReferences] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    void Promise.all([api.getMemoryConfig(), api.getMemoryTask()]).then(([nextConfig, nextTask]) => {
      setConfig(nextConfig)
      setAutoPrompt(nextConfig.auto_prompt)
      setManualPrompt(nextConfig.manual_prompt)
      setTask(nextTask)
    }).catch((reason: Error) => setError(reason.message))
    const timer = window.setInterval(() => {
      void api.getMemoryTask().then(setTask).catch(() => undefined)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [open])

  useEffect(() => {
    if (!open) return
    setDocument(null)
    setVersions([])
    void Promise.all([api.getMemoryDocument(target), api.listMemoryVersions(target)]).then(([nextDocument, nextVersions]) => {
      setDocument(nextDocument)
      setDraft(nextDocument.content)
      setVersions(nextVersions)
    }).catch((reason: Error) => setError(reason.message))
  }, [open, target])

  useEffect(() => {
    if (!open || edit || !task || !['completed', 'partial', 'no_change', 'skipped'].includes(task.status)) return
    let active = true
    void Promise.all([api.getMemoryDocument(target), api.listMemoryVersions(target)]).then(([nextDocument, nextVersions]) => {
      if (!active) return
      setDocument(nextDocument)
      setDraft(nextDocument.content)
      setVersions(nextVersions)
    }).catch((reason: Error) => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [open, target, edit?.id, task?.id, task?.status])

  useEffect(() => {
    if (!edit) return
    return () => { void api.cancelMemoryEdit(edit.id).catch(() => undefined) }
  }, [edit?.id])

  const action = async (work: () => Promise<void>) => {
    setBusy(true)
    setError('')
    try { await work() } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  const switchTarget = (next: Target) => {
    if (edit) return
    setTarget(next)
    setDocument(null)
    setVersions([])
    setSelectedVersion(null)
  }

  const changeConfig = (patch: Partial<MemoryConfig>) => action(async () => {
    const updated = await api.updateMemoryConfig(patch)
    setConfig(updated)
    if (patch.auto_prompt !== undefined) setAutoPrompt(updated.auto_prompt)
    if (patch.manual_prompt !== undefined) setManualPrompt(updated.manual_prompt)
  })

  const startEdit = () => action(async () => {
    const session = await api.beginMemoryEdit(target)
    setEdit(session)
    setDraft(document?.content || '')
  })

  const cancelEdit = () => action(async () => {
    if (edit) await api.cancelMemoryEdit(edit.id)
    setEdit(null)
    setDraft(document?.content || '')
  })

  const save = () => action(async () => {
    if (!edit) return
    const updated = await api.saveMemoryDocument(target, { edit_id: edit.id, revision: edit.revision, content: draft })
    setEdit(null)
    setDocument(updated)
    setVersions(await api.listMemoryVersions(target))
  })

  const restore = () => action(async () => {
    if (!selectedVersion) return
    const session = await api.beginMemoryEdit(target)
    try {
      const updated = await api.restoreMemoryVersion(target, {
        edit_id: session.id, revision: session.revision, version_id: selectedVersion.id,
      })
      setDocument(updated)
      setDraft(updated.content)
      setSelectedVersion(null)
      setVersions(await api.listMemoryVersions(target))
    } catch (reason) {
      await api.cancelMemoryEdit(session.id)
      throw reason
    }
  })

  const run = () => action(async () => {
    if (!config) return
    // The saved prompt is the one both background roles receive.
    const updated = await api.updateMemoryConfig({ manual_prompt: manualPrompt })
    setConfig(updated)
    const started = await api.startMemoryTask({
      ...(start ? { start: new Date(start).toISOString() } : {}),
      ...(end ? { end: new Date(end).toISOString() } : {}),
      targets: [...(updateDocuments ? ['documents' as const] : []),
        ...(updateReferences ? ['references' as const] : [])],
    })
    setTask(started)
  })

  const running = task?.status === 'organizing' || task?.status === 'reviewing' || task?.status === 'committing'
  const length = Array.from(draft).length
  const taskLabels: Record<string, string> = {
    organizing: '整理中', reviewing: '审核中', committing: '保存结果中', completed: '已完成', no_change: '无需修改',
    failed: '失败', cancelled: '已取消',
    partial: '部分完成', skipped: '已检查，未修改',
  }

  return <section className="memory-management">
    <button type="button" className="wide-row" onClick={() => setOpen(!open)} aria-expanded={open}>
      <strong>记忆管理</strong><span>用户信息、长期记忆与技能经验 · 所有项目共用</span>
    </button>
    {open && config && <div className="memory-content">
      <h3>用户与长期记忆</h3>
      <label title="仅控制 user.md 和 memory.md 是否加载到新对话；关闭后仍可查看、编辑和整理。">
        <input type="checkbox" checked={config.enabled} disabled={busy} onChange={event => void changeConfig({ enabled: event.target.checked })} />启用记忆 ⓘ
      </label>
      <label title="控制自动整理 user.md 和 memory.md，与启用记忆独立；关闭后仍可手动整理。">
        <input type="checkbox" checked={config.documents_auto_update} disabled={busy} onChange={event => void changeConfig({ documents_auto_update: event.target.checked })} />自动更新 ⓘ
      </label>
      <div className="memory-tabs">
        <button type="button" disabled={!!edit} aria-pressed={target === 'user'} onClick={() => switchTarget('user')}>user.md</button>
        <button type="button" disabled={!!edit} aria-pressed={target === 'memory'} onClick={() => switchTarget('memory')}>memory.md</button>
      </div>
      {document && <>
        {edit ? <textarea aria-label="编辑记忆文档" value={draft} onChange={event => setDraft(event.target.value)} rows={9} />
          : <pre className="memory-document">{document.content || '（空）'}</pre>}
        <p>{edit ? length : document.length} / {document.limit} 字符
          {edit && length > document.limit && <span> · 超出 {length - document.limit} 字符，不能保存</span>}
        </p>
        {edit ? <div className="memory-actions">
          <button type="button" disabled={busy || length > document.limit} onClick={() => void save()}>保存</button>
          <button type="button" disabled={busy} onClick={() => void cancelEdit()}>取消</button>
        </div> : <button type="button" disabled={busy} onClick={() => void startEdit()}>编辑</button>}
      </>}
      <details><summary>历史版本（最近 8 个）</summary>
        {versions.map(version => <button type="button" key={version.id} disabled={!!edit || busy}
          onClick={() => void action(async () => {
            const loaded = await api.getMemoryVersion(target, version.id)
            setSelectedVersion({ id: version.id, content: loaded.content })
          })}>{version.created_at} · {version.source}</button>)}
        {!versions.length && <p>暂无历史版本</p>}
        {selectedVersion && <div><pre className="memory-document">{selectedVersion.content || '（空）'}</pre>
          <button type="button" disabled={busy || !!edit} onClick={() => void restore()}>用此版本替换当前文档</button></div>}
      </details>
      <h3>技能经验</h3>
      <label title="自动整理技能的 references。关闭后技能仍可使用。">
        <input type="checkbox" checked={config.skills_auto_update} disabled={busy} onChange={event => void changeConfig({ skills_auto_update: event.target.checked })} />自动更新 ⓘ
      </label>
      <h3>补充要求</h3>
      <label>自动更新提示词<textarea value={autoPrompt} rows={3}
        onChange={event => setAutoPrompt(event.target.value)} /></label>
      <div className="memory-actions">
        <button type="button" disabled={busy} onClick={() => void changeConfig({ auto_prompt: autoPrompt })}>保存</button>
        <button type="button" disabled={busy} onClick={() => void changeConfig({ auto_prompt: '' })}>清空</button>
      </div>
      <label>手动更新提示词<textarea value={manualPrompt} rows={3}
        onChange={event => setManualPrompt(event.target.value)} /></label>
      <div className="memory-actions">
        <button type="button" disabled={busy} onClick={() => void changeConfig({ manual_prompt: manualPrompt })}>保存</button>
        <button type="button" disabled={busy} onClick={() => void changeConfig({ manual_prompt: '' })}>清空</button>
      </div>
      <h3>现在更新</h3>
      <label>开始时间<input type="datetime-local" value={start} onChange={event => setStart(event.target.value)} /></label>
      <label>结束时间（默认现在）<input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} /></label>
      <label><input type="checkbox" checked={updateDocuments} disabled={busy}
        onChange={event => setUpdateDocuments(event.target.checked)} />文档记忆</label>
      <label><input type="checkbox" checked={updateReferences} disabled={busy}
        onChange={event => setUpdateReferences(event.target.checked)} />技能经验</label>
      <button type="button" disabled={busy || running || task?.status === 'failed' || !!edit || (!!start && !!end && start > end) ||
        (!updateReferences && !updateDocuments)} onClick={() => void run()}>开始整理</button>
      {task && <p>最近整理：{taskLabels[task.status] || task.status} · {task.created_at}{task.error ? ` · ${task.error}` : ''}</p>}
      {task && <>
        <p>本次对象：{task.allowed_at_start.map(item => ({ user: '用户信息', memory: '长期记忆', references: '技能经验' }[item] || item)).join('、')}
          {task.operation_count != null ? ` · 实际修改 ${task.operation_count} 项` : ''}</p>
        {task.results?.map(item => <p key={item.proposal_index}>提案 {item.proposal_index + 1} · {item.target} · {
          ({ applied: item.changed ? '已修改' : '内容一致', skipped: '审核跳过', blocked: '目标禁止写入' }[item.status] || item.status)
        }：{item.reason}</p>)}
        {task.status === 'failed' && <div className="memory-actions">
          <p>{task.retryable !== false && task.retry_after ? `等待自动重试：${new Date(task.retry_after).toLocaleString()}` : '需要处理上述原因后重试'}；未完成任务保留。</p>
          <button type="button" disabled={busy || !!edit} onClick={() => void action(async () => {
            setTask(await api.controlMemoryTask(task.id, 'retry'))
          })}>立即重试</button>
          <button type="button" disabled={busy || !!edit} onClick={() => void action(async () => {
            setTask(await api.controlMemoryTask(task.id, 'cancel'))
          })}>放弃本次整理</button>
        </div>}
      </>}
      <p>记忆更新及启用状态的变更，在新对话中生效；当前对话不会实时更新。应用重启后恢复对话时，也会加载最新配置和记忆。</p>
    </div>}
    {open && error && <p role="alert">{error}</p>}
  </section>
}
