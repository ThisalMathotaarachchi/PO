export type HealthResponse = {
  ok: boolean
  database: boolean
  ollama: { ok: boolean; host?: string; models?: string[]; error?: string }
  version: string
}

export type Project = {
  id: string
  name: string
  path: string
  last_opened: string
}

export type Workspace = {
  id: string
  path: string
  name: string
}

export type FileEntry = {
  name: string
  path: string
  is_dir: boolean
  size?: number | null
}

export type TaskView = {
  id: string
  prompt: string
  status: string
  summary: string
  error: string
  model: string
  iteration: number
  user_messages: string[]
  project_id: string
  workspace_path: string
}

export type AgentEvent = {
  id?: string
  type: string
  task_id?: string | null
  timestamp?: string
  message?: string
  status?: string
  path?: string | null
  tool?: string | null
  command?: string | null
  metadata?: Record<string, unknown>
}

export type ModelInfo = {
  id: string
  name: string
  family: string
  parameter_size: string
  available: boolean
  capabilities: string[]
}

export type AppSettings = {
  ollama_host: string
  preferred_model: string
  default_workspace: string
  ignore_directories: string[]
  permission_mode: string
  log_level: string
  auto_route: boolean
  auto_approve_yellow: boolean
  appearance: string
  startup: string
  notifications: boolean
}

export type TerminalResult = {
  ok?: boolean
  command?: string
  stdout?: string
  stderr?: string
  exit_code?: number
  source?: string
  error?: string
  status?: string
}

export type FileChange = {
  path: string
  original: string
  current: string
  diff: string
}

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : body.detail?.error ?? JSON.stringify(body.detail ?? body)
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  status: () => request<{ workspace: Workspace | null; task: TaskView | null }>('/api/status'),
  models: () => request<{ ok: boolean; models: ModelInfo[]; selected?: string | null; error?: string }>('/api/models'),
  projects: () => request<{ projects: Project[] }>('/api/projects'),
  createWorkspace: (path: string, name?: string) =>
    request<Workspace>('/api/workspaces', { method: 'POST', body: JSON.stringify({ path, name }) }),
  openWorkspace: (path: string, name?: string) =>
    request<Workspace>('/api/workspaces/open', { method: 'POST', body: JSON.stringify({ path, name }) }),
  activeWorkspace: () => request<Workspace>('/api/workspaces/active'),
  listFiles: (path = '.') => request<{ entries: FileEntry[]; path: string }>(`/api/files?path=${encodeURIComponent(path)}`),
  readFile: (path: string) => request<{ path: string; content: string; truncated?: boolean }>(`/api/files/read?path=${encodeURIComponent(path)}`),
  writeFile: (path: string, content: string) =>
    request('/api/files', { method: 'PUT', body: JSON.stringify({ path, content }) }),
  createFile: (path: string, content = '') =>
    request('/api/files', { method: 'POST', body: JSON.stringify({ path, content }) }),
  mkdir: (path: string) => request('/api/files/mkdir', { method: 'POST', body: JSON.stringify({ path }) }),
  renameFile: (path: string, new_path: string) =>
    request('/api/files/rename', { method: 'POST', body: JSON.stringify({ path, new_path }) }),
  deleteFile: (path: string) => request('/api/files/delete', { method: 'POST', body: JSON.stringify({ path }) }),
  deleteDirectory: (path: string) => request('/api/files/delete-directory', { method: 'POST', body: JSON.stringify({ path }) }),
  search: (q: string, mode: 'code' | 'files' | 'symbol' = 'code') =>
    request<{ matches: Array<string | { path: string; line?: number; text?: string }> }>(
      `/api/search?q=${encodeURIComponent(q)}&mode=${mode}`,
    ),
  runTerminal: (command: string, timeout?: number) =>
    request<TerminalResult>('/api/terminal', { method: 'POST', body: JSON.stringify({ command, timeout }) }),
  runTests: () => request<TerminalResult>('/api/dev/tests', { method: 'POST' }),
  changes: () => request<{ changes: FileChange[] }>('/api/changes'),
  createTask: (prompt: string, workspace_path?: string) =>
    request<TaskView>('/api/tasks', { method: 'POST', body: JSON.stringify({ prompt, workspace_path }) }),
  getTask: (id: string) => request<TaskView>(`/api/tasks/${id}`),
  cancelTask: (id: string) => request<TaskView>(`/api/tasks/${id}/cancel`, { method: 'POST' }),
  approveTask: (id: string, granted: boolean) =>
    request<TaskView>(`/api/tasks/${id}/approval`, { method: 'POST', body: JSON.stringify({ granted }) }),
  taskEvents: (id: string) => request<{ events: AgentEvent[] }>(`/api/tasks/${id}/events`),
  settings: () => request<AppSettings>('/api/settings'),
  saveSettings: (body: Partial<AppSettings>) =>
    request<AppSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(body) }),
  pickFolder: () => request<{ path: string }>('/api/system/pick-folder', { method: 'POST' }),

  // ── Persistent terminal sessions ──────────────────────────────────────────
  terminalSessions: () =>
    request<{ sessions: Array<{ id: string; label: string; alive: boolean }> }>('/api/terminal/sessions'),
  createTerminalSession: (cwd?: string, label?: string) =>
    request<{ id: string; label: string }>('/api/terminal/sessions', {
      method: 'POST',
      body: JSON.stringify({ cwd: cwd ?? null, label: label ?? null }),
    }),
  deleteTerminalSession: (id: string) =>
    request<{ ok: boolean }>(`/api/terminal/sessions/${id}`, { method: 'DELETE' }),

  // ── Project context (.po/instructions.md) ──────────────────────────────
  getProjectInstructions: () =>
    request<{ exists: boolean; content: string }>('/api/project/instructions'),
  scaffoldProjectInstructions: () =>
    request<{ created: boolean; path: string }>('/api/project/instructions/scaffold', { method: 'POST' }),
}

export function wsEventsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = import.meta.env.VITE_WS_HOST || window.location.host
  if (import.meta.env.DEV && !import.meta.env.VITE_WS_HOST) {
    return `ws://127.0.0.1:8000/api/ws/events`
  }
  return `${proto}://${host}/api/ws/events`
}
