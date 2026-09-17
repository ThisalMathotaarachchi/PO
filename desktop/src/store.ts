import { create } from 'zustand'
import type { AgentEvent, AppSettings, Project, TaskView, Workspace } from './api/client'

export type Screen = 'launch' | 'home' | 'workspace' | 'settings'
export type StatusKind = 'ready' | 'working' | 'waiting' | 'error'

export type OpenTab = {
  path: string
  content: string
  original: string
  dirty: boolean
  language: string
  stale?: boolean
}

// ─── Conversation model ───────────────────────────────────────────────────────
// A ConversationTurn represents one exchange: the user's prompt + all Po
// activity produced in response to it. This persists across tasks — only
// cleared when the workspace is closed/changed.

export type ActivityItem = {
  id: string
  text: string
  kind: 'info' | 'success' | 'error' | 'command'
  at: number
}

export type ConversationTurn = {
  id: string
  /** The user's prompt that started this turn */
  userPrompt: string
  /** Flat list of Po activity items for this turn */
  activity: ActivityItem[]
  /** Final outcome — set when the task ends */
  outcome: 'pending' | 'completed' | 'error' | 'cancelled'
  /** Files touched during this turn (for completion result card) */
  changedPaths: string[]
  /** Summary text from the backend when task completes */
  summary: string
  /** Task ID this turn corresponds to */
  taskId: string | null
}

// Legacy ActivityLine kept for ingestEvent compatibility
export type ActivityLine = {
  id: string
  text: string
  kind: 'info' | 'success' | 'error' | 'command'
  role: 'user' | 'po'
  at: number
}

export type TerminalLine = {
  id: string
  text: string
  source: 'po' | 'user' | 'system'
  /** Which terminal session this line belongs to */
  sessionId: string
  at: number
}

export type TerminalSession = {
  id: string
  label: string
  /** Working directory — tracked by the frontend for display only */
  cwd: string
}

export type ApprovalRequest = {
  taskId: string
  message: string
  command?: string
  tool?: string
  level?: string
}

type PoState = {
  screen: Screen
  bootError: string | null
  projects: Project[]
  workspace: Workspace | null
  settings: AppSettings | null
  status: StatusKind
  agentStatus: string
  task: TaskView | null

  // ── Persistent conversation history ──
  conversation: ConversationTurn[]
  /** ID of the currently active (in-progress) turn, null when idle */
  activeTurnId: string | null

  approval: ApprovalRequest | null
  tabs: OpenTab[]
  activePath: string | null
  explorerRefresh: number

  // ── Multi-session terminal ──
  terminalSessions: TerminalSession[]
  activeTerminalId: string
  terminalLines: TerminalLine[]

  promptDraft: string
  showDiff: boolean
  paletteOpen: boolean
  pendingAsk: string | null

  // ── Actions ──
  setScreen: (s: Screen) => void
  setBootError: (e: string | null) => void
  setProjects: (p: Project[]) => void
  setWorkspace: (w: Workspace | null) => void
  setSettings: (s: AppSettings | null) => void
  setStatus: (s: StatusKind) => void
  setAgentStatus: (s: string) => void
  setTask: (t: TaskView | null) => void

  startTurn: (prompt: string, taskId: string) => string   // returns new turn id
  pushTurnActivity: (text: string, kind?: ActivityItem['kind']) => void
  completeTurn: (outcome: ConversationTurn['outcome'], summary?: string) => void
  clearConversation: () => void

  /** @deprecated - kept for legacy call sites; maps to pushTurnActivity */
  pushActivity: (text: string, kind?: ActivityLine['kind'], role?: ActivityLine['role']) => void
  /** @deprecated - kept for legacy call sites; no-ops (conversation is persistent) */
  clearActivity: () => void
  /** Derived read: flattened activity lines for the current active turn */
  readonly activity: ActivityLine[]

  setApproval: (a: ApprovalRequest | null) => void
  openTab: (tab: OpenTab) => void
  updateTab: (path: string, patch: Partial<OpenTab>) => void
  closeTab: (path: string) => void
  setActivePath: (path: string | null) => void
  bumpExplorer: () => void

  // Terminal session management
  addTerminalSession: () => string   // returns new turn id
  removeTerminalSession: (id: string) => void
  setActiveTerminal: (id: string) => void
  clearTerminalSession: (id: string) => void
  pushTerminal: (text: string, source?: TerminalLine['source'], sessionId?: string) => void
  /** Register a session whose ID was created by the backend */
  registerTerminalSession: (id: string, label: string) => void

  setPromptDraft: (v: string) => void
  setShowDiff: (v: boolean) => void
  setPaletteOpen: (v: boolean) => void
  setPendingAsk: (v: string | null) => void
  ingestEvent: (event: AgentEvent) => void
}

function langFor(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    ts: 'typescript', tsx: 'typescript',
    js: 'javascript', jsx: 'javascript',
    py: 'python', json: 'json', md: 'markdown',
    css: 'css', html: 'html',
    yml: 'yaml', yaml: 'yaml', toml: 'toml',
    rs: 'rust', go: 'go',
  }
  return map[ext] ?? 'plaintext'
}

export function languageForPath(path: string): string {
  return langFor(path)
}

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

const INITIAL_TERMINAL_LINES: TerminalLine[] = []  // starts empty — prompt is rendered by the PTY

export const usePoStore = create<PoState>((set, get) => ({
  screen: 'launch',
  bootError: null,
  projects: [],
  workspace: null,
  settings: null,
  status: 'ready',
  agentStatus: 'IDLE',
  task: null,

  conversation: [],
  activeTurnId: null,

  approval: null,
  tabs: [],
  activePath: null,
  explorerRefresh: 0,

  terminalSessions: [],
  activeTerminalId: '',
  terminalLines: INITIAL_TERMINAL_LINES,

  promptDraft: '',
  showDiff: false,
  paletteOpen: false,
  pendingAsk: null,

  // ── Derived activity (current active turn flattened to ActivityLine[]) ──
  // This getter is computed on each access; it's the bridge between the new
  // conversation model and any legacy code that reads `activity`.
  get activity(): ActivityLine[] {
    const s = get()
    const turn = s.activeTurnId
      ? s.conversation.find((t) => t.id === s.activeTurnId)
      : s.conversation[s.conversation.length - 1]
    if (!turn) return []
    return turn.activity.map((a) => ({
      id: a.id,
      text: a.text,
      kind: a.kind,
      role: 'po' as const,
      at: a.at,
    }))
  },

  // ── Conversation actions ──

  startTurn: (prompt, taskId) => {
    const id = makeId()
    const turn: ConversationTurn = {
      id,
      userPrompt: prompt,
      activity: [],
      outcome: 'pending',
      changedPaths: [],
      summary: '',
      taskId,
    }
    set((s) => ({ conversation: [...s.conversation, turn], activeTurnId: id }))
    return id
  },

  pushTurnActivity: (text, kind = 'info') => {
    if (!text.trim()) return
    const { activeTurnId, conversation } = get()
    if (!activeTurnId) return
    const item: ActivityItem = { id: makeId(), text, kind, at: Date.now() }
    set({
      conversation: conversation.map((t) =>
        t.id === activeTurnId
          ? { ...t, activity: dedupeAppend(t.activity, item) }
          : t,
      ),
    })
  },

  completeTurn: (outcome, summary) => {
    const { activeTurnId, conversation } = get()
    if (!activeTurnId) return
    set({
      conversation: conversation.map((t) =>
        t.id === activeTurnId ? { ...t, outcome, summary: summary ?? t.summary } : t,
      ),
      activeTurnId: null,
    })
  },

  clearConversation: () => set({ conversation: [], activeTurnId: null }),

  // ── Legacy shims ──

  pushActivity: (text, kind = 'info', role = 'po') => {
    if (!text.trim()) return
    if (role === 'user') return   // user messages come from startTurn, not pushActivity
    get().pushTurnActivity(text, kind)
  },

  clearActivity: () => {
    // No-op: conversation is now persistent. WorkspaceScreen.submitPrompt calls
    // startTurn() instead, which creates a new conversation entry.
  },

  // ── Standard setters ──

  setScreen: (screen) => set({ screen }),
  setBootError: (bootError) => set({ bootError }),
  setProjects: (projects) => set({ projects }),
  setWorkspace: (workspace) => {
    const prev = get().workspace
    const idChanged = workspace?.id !== prev?.id
    if (idChanged) {
      // Switching to a different project: clear all per-workspace UI state
      // so the new project starts clean rather than showing the previous project's data.
      set({
        workspace,
        conversation: [],
        activeTurnId: null,
        task: null,
        approval: null,
        agentStatus: 'IDLE',
        status: 'ready',
        tabs: [],
        activePath: null,
        explorerRefresh: 0,
        terminalSessions: [],
        activeTerminalId: '',
        terminalLines: [],
      })
    } else {
      set({ workspace })
    }
  },
  setSettings: (settings) => set({ settings }),
  setStatus: (status) => set({ status }),
  setAgentStatus: (agentStatus) => set({ agentStatus }),
  setTask: (task) => set({ task }),
  setApproval: (approval) => set({ approval, status: approval ? 'waiting' : get().status }),

  openTab: (tab) => {
    const existing = get().tabs.find((t) => t.path === tab.path)
    if (existing) { set({ activePath: tab.path }); return }
    set({ tabs: [...get().tabs, tab], activePath: tab.path })
  },
  updateTab: (path, patch) =>
    set({ tabs: get().tabs.map((t) => (t.path === path ? { ...t, ...patch } : t)) }),
  closeTab: (path) => {
    const tabs = get().tabs.filter((t) => t.path !== path)
    const activePath = get().activePath === path ? (tabs[tabs.length - 1]?.path ?? null) : get().activePath
    set({ tabs, activePath })
  },
  setActivePath: (activePath) => set({ activePath }),
  bumpExplorer: () => set({ explorerRefresh: get().explorerRefresh + 1 }),

  // ── Terminal sessions ──

  addTerminalSession: () => {
    // Creates a placeholder session in the UI. WorkspaceScreen will call
    // api.createTerminalSession() and then registerTerminalSession() with the
    // real backend ID once the PTY is ready.
    const id = `terminal-${makeId()}`
    const sessions = get().terminalSessions
    const n = sessions.length + 1
    const session: TerminalSession = { id, label: `PowerShell ${n}`, cwd: '' }
    set({ terminalSessions: [...sessions, session], activeTerminalId: id })
    return id
  },

  registerTerminalSession: (id: string, label: string) => {
    // Called after the backend confirms the PTY session was created.
    // Replaces the placeholder or adds if not found.
    const existing = get().terminalSessions.find((s) => s.id === id)
    if (existing) {
      set({ terminalSessions: get().terminalSessions.map((s) => s.id === id ? { ...s, label } : s) })
    } else {
      const session: TerminalSession = { id, label, cwd: '' }
      set({ terminalSessions: [...get().terminalSessions, session], activeTerminalId: id })
    }
  },

  removeTerminalSession: (id) => {
    // Note: WorkspaceScreen is responsible for calling api.deleteTerminalSession(id)
    // before or after calling this. The store only handles UI state.
    const sessions = get().terminalSessions.filter((s) => s.id !== id)
    if (sessions.length === 0) {
      // Keep at least one slot — WorkspaceScreen will create a replacement
      const newId = `terminal-${makeId()}`
      const newSession: TerminalSession = { id: newId, label: 'PowerShell 1', cwd: '' }
      set({
        terminalSessions: [newSession],
        activeTerminalId: newId,
        terminalLines: get().terminalLines.filter((l) => l.sessionId !== id),
      })
      return
    }
    const newActive = get().activeTerminalId === id ? sessions[sessions.length - 1].id : get().activeTerminalId
    set({
      terminalSessions: sessions,
      activeTerminalId: newActive,
      terminalLines: get().terminalLines.filter((l) => l.sessionId !== id),
    })
  },

  setActiveTerminal: (id) => set({ activeTerminalId: id }),

  clearTerminalSession: (id) =>
    set({ terminalLines: get().terminalLines.filter((l) => l.sessionId !== id) }),

  pushTerminal: (text, source = 'system', sessionId) => {
    const sid = sessionId ?? get().activeTerminalId
    set({
      terminalLines: [
        ...get().terminalLines.slice(-2000),
        { id: makeId(), text, source, sessionId: sid, at: Date.now() },
      ],
    })
  },

  setPromptDraft: (promptDraft) => set({ promptDraft }),
  setShowDiff: (showDiff) => set({ showDiff }),
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setPendingAsk: (pendingAsk) => set({ pendingAsk }),

  // ── WebSocket event ingestion ──

  ingestEvent: (event) => {
    const type = event.type
    const msg = (event.message || '').trim()

    if (type === 'STATE_CHANGED' && event.metadata?.state) {
      set({ agentStatus: String(event.metadata.state) })
      const state = String(event.metadata.state)
      if (['COMPLETED', 'IDLE'].includes(state)) set({ status: 'ready' })
      else if (state === 'WAITING_FOR_APPROVAL') set({ status: 'waiting' })
      else if (state === 'ERROR' || state === 'CANCELLED') set({ status: 'error' })
      else set({ status: 'working' })
    }

    if (type === 'USER_MESSAGE' && msg) get().pushTurnActivity(msg)

    if (type === 'APPROVAL_REQUIRED') {
      set({
        approval: {
          taskId: event.task_id || get().task?.id || '',
          message: msg || 'Po needs approval',
          command: event.command || undefined,
          tool: event.tool || undefined,
          level: typeof event.metadata?.level === 'string' ? event.metadata.level : undefined,
        },
        status: 'waiting',
      })
      get().pushTurnActivity(msg || 'Waiting for approval…')
    }

    if (type === 'APPROVAL_GRANTED' || type === 'APPROVAL_DENIED') set({ approval: null })

    if (type === 'COMMAND_STARTED' && event.command) {
      // Agent commands go to terminal with 'po' source (all sessions visible)
      get().pushTerminal(`$ ${event.command}`, 'po', get().activeTerminalId)
      if (msg) get().pushTurnActivity(msg)
    }

    if (type === 'COMMAND_COMPLETED') {
      const meta = event.metadata || {}
      if (meta.exit_code !== undefined) {
        get().pushTerminal(`exit ${String(meta.exit_code)}`, 'po', get().activeTerminalId)
      }
      if (msg) get().pushTurnActivity(msg, event.status === 'ok' ? 'success' : 'error')
    }

    if (type === 'TEST_STARTED' && msg) get().pushTurnActivity(msg)
    if (type === 'TEST_COMPLETED' && msg) get().pushTurnActivity(msg, event.status === 'ok' ? 'success' : 'error')

    if (type === 'FILE_CHANGED' && event.path) {
      get().bumpExplorer()
      // Track changed path in the active turn for the completion result card
      const { activeTurnId, conversation } = get()
      if (activeTurnId && event.path) {
        set({
          conversation: conversation.map((t) =>
            t.id === activeTurnId && !t.changedPaths.includes(event.path!)
              ? { ...t, changedPaths: [...t.changedPaths, event.path!] }
              : t,
          ),
        })
      }
      if (msg) get().pushTurnActivity(msg || `Updated ${event.path}`)
      const tab = get().tabs.find((t) => t.path === event.path)
      if (tab && !tab.dirty) {
        set({
          tabs: get().tabs.map((t) =>
            t.path === event.path ? { ...t, stale: true } : t,
          ),
        })
      }
    }

    if (type === 'FILE_READ' && msg) get().pushTurnActivity(msg)

    if (type === 'TASK_COMPLETED') {
      set({ status: 'ready', agentStatus: 'COMPLETED', approval: null })
      const summary = msg || 'Done.'
      get().pushTurnActivity(summary, 'success')
      get().completeTurn('completed', summary)
    }

    if (type === 'TASK_FAILED') {
      set({ status: 'error', agentStatus: 'ERROR' })
      const errMsg = msg || 'Something went wrong.'
      get().pushTurnActivity(errMsg, 'error')
      get().completeTurn('error', errMsg)
    }

    if (type === 'TASK_CANCELLED') {
      set({ status: 'ready', agentStatus: 'CANCELLED', approval: null })
      get().pushTurnActivity('Cancelled.', 'info')
      get().completeTurn('cancelled', 'Cancelled.')
    }

    if (type === 'ERROR_DETECTED' && msg) get().pushTurnActivity(msg, 'error')
    if (type === 'FIX_STARTED' && msg) get().pushTurnActivity(msg)
    if (type === 'TOOL_STARTED' && msg) get().pushTurnActivity(msg)
  },
}))

// ── Helpers ──

function dedupeAppend(items: ActivityItem[], next: ActivityItem): ActivityItem[] {
  const last = items[items.length - 1]
  if (last && last.text === next.text && last.kind === next.kind) return items
  return [...items.slice(-80), next]
}
