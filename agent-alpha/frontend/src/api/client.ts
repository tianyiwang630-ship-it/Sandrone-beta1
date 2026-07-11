import type {
  CapabilityItem,
  ChatStart,
  ChatStatus,
  FileContent,
  FileInfo,
  Project,
  Session,
  SessionDetail,
  SessionEvent,
  Settings,
  UploadConflictItem,
  User,
} from '../types'

type SettingsUpdate = Partial<Settings> & {
  llm_api_key?: string
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    cache: 'no-store',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const data = await response.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data)
    } catch {
      // Keep HTTP status text.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  listProjects: () => request<Project[]>('/projects'),
  createProject: (body: { name?: string; workspace_path?: string }) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(body) }),
  updateProject: (projectId: string, body: Partial<Project>) =>
    request<Project>(`/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProject: (projectId: string) => request<{ ok: boolean }>(`/projects/${projectId}`, { method: 'DELETE' }),
  pickProjectFolder: () => request<{ path: string | null }>('/projects/pick-folder'),
  listProjectSessions: (projectId: string) =>
    request<{ sessions: Session[]; total: number }>(`/projects/${projectId}/sessions`),
  createSession: (projectId: string) =>
    request<Session>('/sessions', { method: 'POST', body: JSON.stringify({ project_id: projectId }) }),
  getSession: (sessionId: string) => request<SessionDetail>(`/sessions/${sessionId}`),
  updateSession: (sessionId: string, body: Partial<Session>) =>
    request<Session>(`/sessions/${sessionId}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteSession: (sessionId: string) => request<{ ok: boolean }>(`/sessions/${sessionId}`, { method: 'DELETE' }),
  getSessionEvents: (sessionId: string) => request<{ events: SessionEvent[] }>(`/sessions/${sessionId}/events`),
  sendMessage: (sessionId: string, message: string) =>
    request<ChatStart>('/chat', { method: 'POST', body: JSON.stringify({ session_id: sessionId, message }) }),
  compactSession: (sessionId: string) =>
    request<ChatStart>('/chat/compact', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }),
  getChatStatus: (requestId: string) => request<ChatStatus>(`/chat/status/${requestId}`),
  getSessionActiveRun: (sessionId: string) => request<ChatStatus>(`/chat/session-status/${sessionId}`),
  interrupt: (sessionId: string) => request<{ ok: boolean }>(`/chat/interrupt/${sessionId}`, { method: 'POST' }),
  getSettings: () => request<Settings>('/settings'),
  updateSettings: (body: SettingsUpdate) =>
    request<Settings>('/settings', { method: 'PATCH', body: JSON.stringify(body) }),
  listUsers: () => request<User[]>('/users'),
  updateCurrentUser: (body: { name: string }) =>
    request<User>('/users/current', { method: 'PATCH', body: JSON.stringify(body) }),
  listCapabilities: () => request<{ items: CapabilityItem[] }>('/meta/capabilities'),
  listFiles: (projectId: string, path?: string) => {
    const query = new URLSearchParams({ project_id: projectId })
    if (path) query.set('path', path)
    return request<{ root: string; path: string; items: FileInfo[] }>(`/files/tree?${query.toString()}`)
  },
  readFile: (projectId: string, path: string) => {
    const query = new URLSearchParams({ project_id: projectId, path })
    return request<FileContent>(`/files/content?${query.toString()}`)
  },
  rawFileUrl: (projectId: string, path: string) => {
    const query = new URLSearchParams({ project_id: projectId, path })
    return `/api/files/raw?${query.toString()}`
  },
  assetBaseUrl: (projectId: string, path: string) => {
    const parts = path.split('/').filter(Boolean)
    parts.pop()
    const encodedParts = parts.map((part) => encodeURIComponent(part))
    const prefix = encodedParts.length ? `${encodedParts.join('/')}/` : ''
    return `/api/files/assets/${encodeURIComponent(projectId)}/${prefix}`
  },
  checkFileConflicts: (body: { project_id: string; target_path: string; relative_paths: string[] }) =>
    request<{ has_conflicts: boolean; conflicts: UploadConflictItem[] }>('/files/conflicts/check', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  uploadFile: (body: FormData) =>
    fetch('/api/files/upload', {
      method: 'POST',
      body,
    }).then(async (response) => {
      if (!response.ok) {
        let detail = response.statusText
        try {
          const data = await response.json()
          detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data)
        } catch {
          // Keep HTTP status text.
        }
        throw new Error(detail)
      }
      return response.json() as Promise<FileInfo>
    }),
  createFolder: (body: { project_id: string; target_path: string; name: string }) =>
    request<FileInfo>('/files/folders', { method: 'POST', body: JSON.stringify(body) }),
  openInFolder: (body: { project_id: string; path: string }) =>
    request<{ ok: boolean }>('/files/open-in-folder', { method: 'POST', body: JSON.stringify(body) }),
}
