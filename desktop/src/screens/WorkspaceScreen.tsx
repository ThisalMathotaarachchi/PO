/**
 * WorkspaceScreen — Po IDE main workspace.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────────────────┐
 *   │  PO  File  Edit  Selection  View  Go  Run  Terminal  Help   │  ← navbar
 *   ├──────────────┬──────────────────────────────┬───────────────┤
 *   │              │                              │               │
 *   │   PO AGENT   │         EDITOR               │   EXPLORER    │
 *   │  (full left) │                              │  (full right) │
 *   │              ├──────────────────────────────┤               │
 *   │              │       TERMINAL               │               │
 *   └──────────────┴──────────────────────────────┴───────────────┘
 *
 * Menu system: position:fixed dropdowns so Monaco/panels can never clip them.
 * Mouse-enter with any menu open switches the active menu immediately.
 */

import { api } from '../api/client'
import { AgentPanel } from '../components/AgentPanel'
import { CodeEditor } from '../components/CodeEditor'
import { CommandPalette } from '../components/CommandPalette'
import { DiffReview } from '../components/DiffReview'
import { Explorer } from '../components/Explorer'
import { FileSearch } from '../components/FileSearch'
import { PoMark } from '../components/PoMark'
import { TerminalPanel } from '../components/TerminalPanel'
import { statusLabel } from '../components/PoOrb'
import { useEventSocket } from '../hooks/useEventSocket'
import { languageForPath, usePoStore } from '../store'
import {
  useCallback, useEffect, useMemo, useRef, useState
} from 'react'

// ─── Dropdown menu ───────────────────────────────────────────────────────────
// Uses position:fixed so nothing (Monaco, xterm, Explorer) can clip it.
// The open/close logic lives in the NavBar — individual menus are pure display.

type MenuEntry =
  | { label: string; shortcut?: string; action: () => void; disabled?: boolean }
  | { separator: true }

interface DropdownProps {
  items: MenuEntry[]
  anchorRect: DOMRect | null
  onClose: () => void
}

function Dropdown({ items, anchorRect, onClose }: DropdownProps) {
  const ref = useRef<HTMLDivElement>(null)

  // Position below the trigger button
  const style = anchorRect
    ? {
        top:  anchorRect.bottom + 2,
        left: anchorRect.left,
      }
    : { top: 36, left: 0 }

  // Close on outside click or Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown, true)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onDown, true)
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      className="menu-dropdown"
      style={{ ...style, position: 'fixed' }}
      // Stop propagation so the outside-click handler above doesn't fire
      onMouseDown={(e) => e.stopPropagation()}
    >
      {items.map((item, i) =>
        'separator' in item ? (
          <div key={`sep-${i}`} className="menu-separator" />
        ) : (
          <button
            key={item.label}
            type="button"
            className={`menu-item w-full text-left ${item.disabled ? 'menu-item--disabled' : ''}`}
            onClick={() => {
              if (!item.disabled) {
                item.action()
                onClose()
              }
            }}
          >
            <span>{item.label}</span>
            {item.shortcut && <span className="menu-shortcut">{item.shortcut}</span>}
          </button>
        ),
      )}
    </div>
  )
}

// ─── NavBar ───────────────────────────────────────────────────────────────────

interface NavBarProps {
  workspaceName?: string
  status: 'ready' | 'working' | 'waiting' | 'error'
  onHome: () => void
  onSettings: () => void
  onFileSearch: () => void
  onPalette: () => void
  onShowDiff: () => void
  onRefreshExplorer: () => void
  onNewTerminal: () => void
  onCloseTerminal: () => void
  onNewFile: () => void
}

function NavBar({
  workspaceName,
  status,
  onHome,
  onSettings,
  onFileSearch,
  onPalette,
  onShowDiff,
  onRefreshExplorer,
  onNewTerminal,
  onCloseTerminal,
  onNewFile,
}: NavBarProps) {
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const [anchorRects, setAnchorRects] = useState<Record<string, DOMRect>>({})
  const triggerRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  function openDropdown(name: string) {
    const btn = triggerRefs.current[name]
    if (btn) setAnchorRects((r) => ({ ...r, [name]: btn.getBoundingClientRect() }))
    setOpenMenu(name)
  }

  function closeDropdown() { setOpenMenu(null) }

  const menus: Record<string, MenuEntry[]> = {
    File: [
      { label: 'New File',         shortcut: 'Ctrl+N',   action: onNewFile },
      { label: 'Open File…',       shortcut: 'Ctrl+P',   action: onFileSearch },
      { separator: true },
      { label: 'Save',             shortcut: 'Ctrl+S',   action: () => {/* CodeEditor handles Ctrl+S */}, disabled: true },
      { separator: true },
      { label: 'Go to Home',       action: onHome },
      { label: 'Settings',         action: onSettings },
    ],
    Edit: [
      { label: 'Undo',   shortcut: 'Ctrl+Z',   action: () => document.execCommand('undo'),   disabled: true },
      { label: 'Redo',   shortcut: 'Ctrl+Y',   action: () => document.execCommand('redo'),   disabled: true },
      { separator: true },
      { label: 'Find',   shortcut: 'Ctrl+F',   action: () => {/* Monaco handles */},         disabled: true },
      { label: 'Replace',shortcut: 'Ctrl+H',   action: () => {/* Monaco handles */},         disabled: true },
    ],
    Selection: [
      { label: 'Select All',          shortcut: 'Ctrl+A',        action: () => {}, disabled: true },
      { label: 'Expand Selection',    shortcut: 'Alt+⇧→',        action: () => {}, disabled: true },
      { separator: true },
      { label: 'Add Cursor Above',    shortcut: 'Ctrl+Alt+↑',    action: () => {}, disabled: true },
      { label: 'Add Cursor Below',    shortcut: 'Ctrl+Alt+↓',    action: () => {}, disabled: true },
    ],
    View: [
      { label: 'Command Palette',   shortcut: 'Ctrl+⇧P',  action: onPalette },
      { label: 'Open File…',        shortcut: 'Ctrl+P',   action: onFileSearch },
      { separator: true },
      { label: 'Review Changes',    action: onShowDiff },
      { label: 'Refresh Explorer',  action: onRefreshExplorer },
    ],
    Go: [
      { label: 'Go to File…',       shortcut: 'Ctrl+P',   action: onFileSearch },
      { label: 'Go to Symbol…',     shortcut: 'Ctrl+⇧O',  action: onPalette,   disabled: true },
      { separator: true },
      { label: 'Go Back',           shortcut: 'Alt+←',    action: () => {},    disabled: true },
      { label: 'Go Forward',        shortcut: 'Alt+→',    action: () => {},    disabled: true },
    ],
    Run: [
      { label: 'Run Tests',   action: () => {} /* wired via palette */ },
      { label: 'Build',       action: () => {}, disabled: true },
      { separator: true },
      { label: 'Ask Po to Run Tests', action: onPalette },
    ],
    Terminal: [
      { label: 'New Terminal',     shortcut: 'Ctrl+⇧`', action: onNewTerminal },
      { separator: true },
      { label: 'Close Terminal',   action: onCloseTerminal },
    ],
    Help: [
      { label: 'Command Palette',  shortcut: 'Ctrl+⇧P',  action: onPalette },
      { separator: true },
      { label: 'Po on GitHub',     action: () => window.open('https://github.com', '_blank') },
    ],
  }

  const statusDotClass =
    status === 'working' ? 'status-dot status-dot--working' :
    status === 'waiting' ? 'status-dot status-dot--waiting' :
    status === 'error'   ? 'status-dot status-dot--error' :
    'status-dot status-dot--ready'

  return (
    <nav className="navbar" style={{ userSelect: 'none' }}>
      {/* Po mark + wordmark */}
      <button
        type="button"
        className="navbar-brand"
        onClick={onHome}
        title="Go to Home"
      >
        <PoMark size={18} color="#1C1917" />
        <span className="navbar-wordmark">Po</span>
      </button>

      {/* Menu triggers */}
      {Object.entries(menus).map(([name]) => (
        <button
          key={name}
          type="button"
          ref={(el) => { triggerRefs.current[name] = el }}
          className="menu-trigger"
          data-open={openMenu === name ? 'true' : undefined}
          onMouseDown={() => openMenu === name ? closeDropdown() : openDropdown(name)}
          onMouseEnter={() => { if (openMenu && openMenu !== name) openDropdown(name) }}
        >
          {name}
        </button>
      ))}

      {/* Workspace name + status */}
      <div className="ml-auto flex items-center gap-3">
        {workspaceName && (
          <span
            className="truncate max-w-[200px]"
            style={{ fontSize: 12, color: 'var(--color-ink-3)' }}
          >
            {workspaceName}
          </span>
        )}
        <span className="flex items-center gap-1.5" style={{ fontSize: 11, color: 'var(--color-ink-3)' }}>
          <span className={statusDotClass} />
          {statusLabel(status)}
        </span>
      </div>

      {/* Active dropdown (portal-style via position:fixed) */}
      {openMenu && menus[openMenu] && (
        <Dropdown
          items={menus[openMenu]}
          anchorRect={anchorRects[openMenu] ?? null}
          onClose={closeDropdown}
        />
      )}
    </nav>
  )
}

// ─── Resize hook ──────────────────────────────────────────────────────────────

type DragTarget = 'agent' | 'explorer' | 'terminal-h' | null

function useResize(
  setAgentWidth:     (v: number) => void,
  setExplorerWidth:  (v: number) => void,
  setTerminalHeight: (v: number) => void,
) {
  const dragging = useRef<DragTarget>(null)

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return
      if (dragging.current === 'agent') {
        setAgentWidth(Math.min(540, Math.max(220, e.clientX)))
      } else if (dragging.current === 'explorer') {
        setExplorerWidth(Math.min(540, Math.max(160, window.innerWidth - e.clientX)))
      } else if (dragging.current === 'terminal-h') {
        setTerminalHeight(Math.min(700, Math.max(80, window.innerHeight - e.clientY)))
      }
    }
    const onUp = () => { dragging.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup',   onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup',   onUp)
    }
  }, [setAgentWidth, setExplorerWidth, setTerminalHeight])

  return dragging
}

// ─── Git badge ────────────────────────────────────────────────────────────────

type GitInfo = { branch: string; dirty: number }

function useGitStatus(active: boolean): GitInfo | null {
  const [info, setInfo] = useState<GitInfo | null>(null)
  useEffect(() => {
    if (!active) return
    let cancelled = false
    void (async () => {
      try {
        const res = await api.runTerminal('git status --short --branch', 5)
        if (cancelled) return
        const lines = ((res.stdout ?? '') as string).split('\n').filter(Boolean)
        const branchLine = lines[0] ?? ''
        const branch = branchLine.startsWith('##')
          ? (branchLine.slice(3).split('...')[0].trim() || 'HEAD')
          : ''
        if (!branch) { setInfo(null); return }
        setInfo({ branch, dirty: lines.slice(1).filter((l) => l.trim()).length })
      } catch { setInfo(null) }
    })()
    return () => { cancelled = true }
  }, [active])
  return info
}

// ─── WorkspaceScreen ─────────────────────────────────────────────────────────

export function WorkspaceScreen() {
  const workspace          = usePoStore((s) => s.workspace)
  const status             = usePoStore((s) => s.status)
  const setScreen          = usePoStore((s) => s.setScreen)
  const setTask            = usePoStore((s) => s.setTask)
  const setStatus          = usePoStore((s) => s.setStatus)
  const startTurn          = usePoStore((s) => s.startTurn)
  const setShowDiff        = usePoStore((s) => s.setShowDiff)
  const showDiff           = usePoStore((s) => s.showDiff)
  const paletteOpen        = usePoStore((s) => s.paletteOpen)
  const setPaletteOpen     = usePoStore((s) => s.setPaletteOpen)
  const pendingAsk         = usePoStore((s) => s.pendingAsk)
  const setPendingAsk      = usePoStore((s) => s.setPendingAsk)
  const setPromptDraft     = usePoStore((s) => s.setPromptDraft)
  const bumpExplorer       = usePoStore((s) => s.bumpExplorer)
  const openTab            = usePoStore((s) => s.openTab)
  const sessions           = usePoStore((s) => s.terminalSessions)
  const activeTerminalId   = usePoStore((s) => s.activeTerminalId)
  const registerSession    = usePoStore((s) => s.registerTerminalSession)
  const removeSessionStore = usePoStore((s) => s.removeTerminalSession)

  const [agentWidth,     setAgentWidth]     = useState(300)
  const [explorerWidth,  setExplorerWidth]  = useState(260)
  const [terminalHeight, setTerminalHeight] = useState(220)
  const [showFileSearch, setShowFileSearch] = useState(false)

  const dragging = useResize(setAgentWidth, setExplorerWidth, setTerminalHeight)
  useGitStatus(Boolean(workspace))  // just for sidebar badge elsewhere if needed

  useEventSocket(Boolean(workspace))

  // Create initial terminal session when workspace opens
  const initialSessionCreated = useRef(false)
  useEffect(() => {
    if (!workspace || initialSessionCreated.current || sessions.length > 0) return
    initialSessionCreated.current = true
    void (async () => {
      try {
        const result = await api.createTerminalSession(workspace.path)
        registerSession(result.id, result.label)
      } catch (e) {
        console.warn('Could not create terminal session:', e)
      }
    })()
  }, [workspace, sessions.length, registerSession])

  useEffect(() => {
    initialSessionCreated.current = false
  }, [workspace?.id])

  useEffect(() => {
    if (pendingAsk) { setPromptDraft(pendingAsk); setPendingAsk(null) }
  }, [pendingAsk, setPendingAsk, setPromptDraft])

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const ctrl = e.ctrlKey || e.metaKey
      if (ctrl && e.shiftKey && e.key.toLowerCase() === 'p') { e.preventDefault(); setPaletteOpen(true) }
      if (ctrl && !e.shiftKey && e.key.toLowerCase() === 'p') { e.preventDefault(); setShowFileSearch(true) }
      if (ctrl && e.shiftKey && e.key === '`') { e.preventDefault(); void addTerminalSession() }
      if (e.key === 'Escape') { setPaletteOpen(false); setShowDiff(false); setShowFileSearch(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPaletteOpen, setShowDiff])

  const addTerminalSession = useCallback(async () => {
    if (!workspace) return
    try {
      const result = await api.createTerminalSession(workspace.path)
      registerSession(result.id, result.label)
    } catch (e) { console.warn('Could not create terminal session:', e) }
  }, [workspace, registerSession])

  const removeTerminalSession = useCallback(async (id: string) => {
    try { await api.deleteTerminalSession(id) } catch { /* already dead */ }
    removeSessionStore(id)
    if (sessions.length <= 1 && workspace) void addTerminalSession()
  }, [sessions.length, workspace, addTerminalSession, removeSessionStore])

  const submitPrompt = useCallback(async (prompt: string) => {
    if (!workspace) return
    setStatus('working')
    const task = await api.createTask(prompt, workspace.path)
    setTask(task)
    startTurn(prompt, task.id)
  }, [workspace, setStatus, setTask, startTurn])

  const handleOpenFile = useCallback(async (path: string) => {
    try {
      const file = await api.readFile(path)
      openTab({ path, content: file.content, original: file.content, dirty: false, language: languageForPath(path) })
    } catch { /* deleted */ }
  }, [openTab])

  const paletteActions = useMemo(() => [
    { id: 'settings',     label: 'Settings',              run: () => setScreen('settings') },
    { id: 'home',         label: 'Go Home',                run: () => setScreen('home') },
    { id: 'diff',         label: 'Review changes',         run: () => setShowDiff(true) },
    { id: 'files',        label: 'Open file (Ctrl+P)',     run: () => setShowFileSearch(true) },
    { id: 'new-terminal', label: 'New terminal',           run: () => void addTerminalSession() },
    { id: 'tests',        label: 'Run tests',              run: () => void submitPrompt('Run the tests and report results.') },
    { id: 'ask',          label: 'Ask Po',                 run: () => setPromptDraft('') },
    { id: 'refresh',      label: 'Refresh explorer',       run: () => bumpExplorer() },
  ], [addTerminalSession, bumpExplorer, setPromptDraft, setScreen, setShowDiff, submitPrompt])

  if (!workspace) {
    return (
      <div className="flex h-full items-center justify-center" style={{ background: 'var(--color-paper)' }}>
        <button
          type="button"
          className="btn-primary"
          onClick={() => setScreen('home')}
        >
          Open a project
        </button>
      </div>
    )
  }

  return (
    <div className="relative flex h-full flex-col overflow-hidden" style={{ background: 'var(--color-paper)' }}>

      {/* ── Application navbar ── */}
      <NavBar
        workspaceName={workspace.name}
        status={status}
        onHome={() => setScreen('home')}
        onSettings={() => setScreen('settings')}
        onFileSearch={() => setShowFileSearch(true)}
        onPalette={() => setPaletteOpen(true)}
        onShowDiff={() => setShowDiff(true)}
        onRefreshExplorer={() => bumpExplorer()}
        onNewTerminal={() => void addTerminalSession()}
        onCloseTerminal={() => activeTerminalId ? void removeTerminalSession(activeTerminalId) : undefined}
        onNewFile={() => setShowFileSearch(true)}
      />

      {/* ── Three-column workspace ── */}
      <div className="flex min-h-0 flex-1">

        {/* LEFT: Po Agent (full height) */}
        <div
          className="agent-panel ruled-paper flex shrink-0 flex-col"
          style={{ width: agentWidth }}
        >
          <AgentPanel onSubmit={submitPrompt} onOpenFile={handleOpenFile} />
        </div>

        {/* Agent ↔ Center divider */}
        <div
          className="panel-divider--col relative shrink-0"
          onMouseDown={() => { dragging.current = 'agent' }}
        />

        {/* CENTER: Editor + Terminal */}
        <div className="ruled-paper flex min-w-0 flex-1 flex-col" style={{ background: 'var(--color-paper)' }}>
          {/* Editor */}
          <div className="min-h-0 flex-1">
            <CodeEditor />
          </div>

          {/* Editor ↔ Terminal divider */}
          <div
            className="panel-divider--row relative shrink-0"
            onMouseDown={() => { dragging.current = 'terminal-h' }}
          />

          {/* Terminal */}
          <div className="shrink-0" style={{ height: terminalHeight }}>
            <TerminalPanel
              onAddSession={() => void addTerminalSession()}
              onRemoveSession={(id) => void removeTerminalSession(id)}
            />
          </div>
        </div>

        {/* Center ↔ Explorer divider */}
        <div
          className="panel-divider--col relative shrink-0"
          onMouseDown={() => { dragging.current = 'explorer' }}
        />

        {/* RIGHT: Explorer (full height) */}
        <div
          className="explorer-panel ruled-paper flex shrink-0 flex-col"
          style={{ width: explorerWidth }}
        >
          <Explorer onAsk={(p) => void submitPrompt(p)} />
        </div>
      </div>

      {/* Overlays */}
      <DiffReview open={showDiff} onClose={() => setShowDiff(false)} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} actions={paletteActions} />
      <FileSearch open={showFileSearch} onClose={() => setShowFileSearch(false)} />
    </div>
  )
}
