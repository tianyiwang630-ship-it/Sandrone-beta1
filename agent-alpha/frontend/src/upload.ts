import { api } from './api/client.ts'
import type { FileInfo } from './types'

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

export async function uploadProjectFiles(
  projectId: string,
  targetPath: string,
  entries: UploadEntry[],
): Promise<FileInfo[]> {
  const uploadedFiles: FileInfo[] = []
  for (const entry of entries) {
    const formData = new FormData()
    formData.set('project_id', projectId)
    formData.set('target_path', targetPath)
    formData.set('relative_path', entry.relativePath)
    formData.set('conflict_strategy', 'rename')
    formData.set('file', entry.file)
    uploadedFiles.push(await api.uploadFile(formData))
  }
  return uploadedFiles
}
