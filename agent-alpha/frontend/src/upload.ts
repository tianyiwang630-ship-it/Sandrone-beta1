import { api } from './api/client.ts'
import type { FileInfo, UploadConflictItem } from './types'

export type ConflictStrategy = 'replace' | 'rename'

export interface UploadEntry {
  file: File
  relativePath: string
}

export function buildFolderFiles(entries: FileList | null): UploadEntry[] {
  const files = Array.from(entries || [])
  return files.map((file) => ({
    file,
    relativePath: ((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name).replace(/\\/g, '/'),
  }))
}

export async function checkProjectUploadConflicts(
  projectId: string,
  targetPath: string,
  entries: UploadEntry[],
): Promise<{ has_conflicts: boolean; conflicts: UploadConflictItem[] }> {
  return api.checkFileConflicts({
    project_id: projectId,
    target_path: targetPath,
    relative_paths: entries.map((entry) => entry.relativePath),
  })
}

export async function uploadProjectFiles(
  projectId: string,
  targetPath: string,
  entries: UploadEntry[],
  strategy?: ConflictStrategy,
): Promise<FileInfo[]> {
  const uploadedFiles: FileInfo[] = []
  for (const entry of entries) {
    const formData = new FormData()
    formData.set('project_id', projectId)
    formData.set('target_path', targetPath)
    formData.set('relative_path', entry.relativePath)
    if (strategy) formData.set('conflict_strategy', strategy)
    formData.set('file', entry.file)
    uploadedFiles.push(await api.uploadFile(formData))
  }
  return uploadedFiles
}
