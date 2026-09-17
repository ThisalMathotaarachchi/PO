/**
 * TerminalPanel — real persistent PowerShell sessions via PTY WebSocket.
 *
 * Each visible tab corresponds to a real PowerShell process on the backend,
 * created via POST /api/terminal/sessions and streamed through
 * WS /api/terminal/sessions/{id}/ws.
 *
 * Output is rendered by xterm.js which handles ANSI escape codes, colours,
 * cursor movement, and all other terminal control sequences correctly.
 *
 * The store tracks session metadata (id, label). The actual process lives on
 * the backend; closing a tab sends DELETE /api/terminal/sessions/{id}.
 */

import { usePoStore } from '../store'
import { useEffect, useRef, useState, useCallback } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

// ── WS URL helper ─────────────────────────────────────────────────────────────

function terminalWsUrl(sessionId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = import.meta.env.DEV
    ? '127.0.0.1:8000'
    : window.location.host
  return `${proto}://${host}/api/terminal/sessions/${sessionId}/ws`
}

// ── Xterm theme — paper/ink terminal matching the rest of Po ─────────────────
// The terminal uses the same warm paper background as the Agent and Explorer,
// giving the workspace a unified "single sheet of paper" feel.
// Text colours use warm ink tones for readability without harsh contrast.

const XTERM_THEME = {
  background:   '#EDE9DF',  // var(--color-paper-2) — same warm paper as agent
  foreground:   '#1C1917',  // var(--color-ink) — main ink colour
  cursor:       '#44403C',  // var(--color-ink-2)
  cursorAccent: '#F3F0E8',  // var(--color-paper)
  selectionBackground: 'rgba(28,25,23,0.15)',
  black:        '#292524',
  red:          '#8B3A2A',  // warm dark red
  green:        '#3A6A3A',  // warm dark green
  yellow:       '#7A5A20',  // warm ochre
  blue:         '#2A4A6A',  // warm dark blue
  magenta:      '#5A2A5A',  // warm dark magenta
  cyan:         '#1A5A5A',  // warm dark teal
  white:        '#44403C',  // var(--color-ink-2)
  brightBlack:  '#78716C',  // var(--color-ink-3)
  brightRed:    '#A84A36',
  brightGreen:  '#4A8A4A',
  brightYellow: '#9A7030',
  brightBlue:   '#3A6A9A',
  brightMagenta:'#7A3A7A',
  brightCyan:   '#2A7A7A',
  brightWhite:  '#1C1917',  // pure ink for bright white
}

// ── Single terminal session component ────────────────────────────────────────

interface SessionProps {
  sessionId: string
  active: boolean
}

function PtySession({ sessionId, active }: SessionProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef      = useRef<Terminal | null>(null)
  const fitRef       = useRef<FitAddon | null>(null)
  const wsRef        = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError]         = useState<string | null>(null)

  const connect = useCallback(() => {
    // Build xterm instance
    const term = new Terminal({
      theme: XTERM_THEME,
      fontFamily: '"JetBrains Mono", "Cascadia Code", "Consolas", monospace',
      fontSize: 12,
      lineHeight: 1.4,
      cursorBlink: true,
      cursorStyle: 'block',
      convertEol: true,
      scrollback: 10000,
      allowProposedApi: true,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    termRef.current  = term
    fitRef.current   = fit

    if (containerRef.current) {
      term.open(containerRef.current)
      fit.fit()
    }

    // WebSocket connection
    const ws = new WebSocket(terminalWsUrl(sessionId))
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setError(null)
      // Send initial size
      const { cols, rows } = term
      ws.send(JSON.stringify({ type: 'resize', cols, rows }))
    }

    ws.onmessage = (e) => {
      if (typeof e.data === 'string') {
        try {
          const frame = JSON.parse(e.data) as { type: string }
          if (frame.type === 'exit') {
            term.writeln('\r\n\x1b[2m[Process exited]\x1b[0m')
            setConnected(false)
          }
        } catch {
          term.write(e.data)
        }
      } else {
        // ArrayBuffer → Uint8Array → terminal
        term.write(new Uint8Array(e.data))
      }
    }

    ws.onerror = () => {
      setError('Terminal connection failed')
      setConnected(false)
    }

    ws.onclose = () => {
      setConnected(false)
    }

    // Forward keystrokes to PTY
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })

    // Resize PTY when terminal element resizes
    const ro = new ResizeObserver(() => {
      try {
        fit.fit()
        if (ws.readyState === WebSocket.OPEN) {
          const { cols, rows } = term
          ws.send(JSON.stringify({ type: 'resize', cols, rows }))
        }
      } catch { /* ignore during teardown */ }
    })
    if (containerRef.current) ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      ws.close()
      term.dispose()
      termRef.current = null
      fitRef.current  = null
      wsRef.current   = null
    }
  }, [sessionId])

  // Connect on mount — cleanup disposes everything
  useEffect(() => {
    const cleanup = connect()
    return cleanup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])  // reconnect if sessionId changes; don't re-run just because connect ref changed

  // Fit when becoming the active tab
  useEffect(() => {
    if (active && fitRef.current) {
      try { fitRef.current.fit() } catch { /* ignore */ }
    }
  }, [active])

  // Focus terminal when tab becomes active
  useEffect(() => {
    if (active && termRef.current) {
      termRef.current.focus()
    }
  }, [active])

  return (
    <div className="relative h-full w-full overflow-hidden" style={{ background: '#EDE9DF' }}>
      {/* Connecting overlay */}
      {!connected && !error && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 10,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(237,233,223,0.85)',
        }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-ink-3)', fontStyle: 'italic' }}>
            Connecting…
          </span>
        </div>
      )}
      {/* Error overlay */}
      {error && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 10,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12,
          background: '#EDE9DF',
        }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-ink-3)' }}>{error}</span>
          <button
            type="button"
            className="btn-ghost"
            style={{ fontSize: 12, padding: '4px 14px' }}
            onClick={() => { setError(null); connect() }}
          >
            Reconnect
          </button>
        </div>
      )}
      {/* xterm.js container */}
      <div
        ref={containerRef}
        className="h-full w-full"
        style={{ padding: '6px 8px' }}
      />
    </div>
  )
}

// ── Root TerminalPanel with session tabs ──────────────────────────────────────

interface TerminalPanelProps {
  /** Called when the + button is clicked — must call api.createTerminalSession */
  onAddSession?: () => void
  /** Called when × is clicked on a tab — must call api.deleteTerminalSession */
  onRemoveSession?: (id: string) => void
}

export function TerminalPanel({ onAddSession, onRemoveSession }: TerminalPanelProps) {
  const sessions         = usePoStore((s) => s.terminalSessions)
  const activeId         = usePoStore((s) => s.activeTerminalId)
  const setActiveSession = usePoStore((s) => s.setActiveTerminal)
  const removeSessionStore = usePoStore((s) => s.removeTerminalSession)

  function handleRemove(id: string) {
    if (onRemoveSession) {
      onRemoveSession(id)
    } else {
      removeSessionStore(id)
    }
  }

  return (
    <div className="flex h-full flex-col" style={{ background: 'transparent' }}>

      {/* ── Session tab strip ── */}
      <div
        className="flex shrink-0 items-center"
        style={{
          background: 'var(--color-paper-2)',
          borderBottom: '1px solid var(--color-border)',
          height: 30,
        }}
      >
        <div className="scrollbar-thin flex min-w-0 flex-1 overflow-x-auto" style={{ height: '100%' }}>
          {sessions.map((s, idx) => {
            // Issue 3: derive display label from current position, not stored label
            const displayLabel = `PowerShell ${idx + 1}`
            const isActive = s.id === activeId
            return (
              <div
                key={s.id}
                className="group flex shrink-0 items-center"
                style={{
                  borderRight: '1px solid var(--color-border)',
                  background: isActive ? 'var(--color-paper-2)' : 'transparent',
                  height: '100%',
                }}
              >
                <button
                  type="button"
                  style={{
                    padding: '0 10px',
                    fontSize: 11,
                    fontFamily: 'var(--font-mono)',
                    color: isActive ? 'var(--color-ink)' : 'var(--color-ink-3)',
                    background: 'none',
                    border: 'none',
                    cursor: 'default',
                    whiteSpace: 'nowrap',
                    height: '100%',
                    borderBottom: isActive ? '2px solid var(--color-ink)' : '2px solid transparent',
                  }}
                  onClick={() => setActiveSession(s.id)}
                >
                  {displayLabel}
                </button>
                {sessions.length > 1 && (
                  <button
                    type="button"
                    style={{
                      paddingRight: 6,
                      fontSize: 11,
                      color: 'var(--color-ink-4)',
                      background: 'none',
                      border: 'none',
                      cursor: 'default',
                    }}
                    title="Close terminal"
                    onClick={(e) => { e.stopPropagation(); handleRemove(s.id) }}
                  >
                    ×
                  </button>
                )}
              </div>
            )
          })}
        </div>

        {/* New session button */}
        <button
          type="button"
          style={{
            flexShrink: 0,
            paddingLeft: 8,
            paddingRight: 8,
            fontSize: 15,
            color: 'var(--color-ink-4)',
            background: 'none',
            border: 'none',
            borderLeft: '1px solid var(--color-border)',
            cursor: 'default',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
          }}
          title="New terminal (Ctrl+Shift+`)"
          onClick={() => onAddSession?.()}
        >
          +
        </button>
      </div>

      {/* ── Session bodies ── */}
      <div className="relative min-h-0 flex-1">
        {sessions.length === 0 && (
          <div
            className="flex h-full items-center justify-center"
            style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-ink-4)', fontStyle: 'italic' }}
          >
            No terminal session. Use Terminal → New Terminal.
          </div>
        )}
        {sessions.map((s) => (
          <div
            key={s.id}
            className="absolute inset-0"
            style={{ visibility: s.id === activeId ? 'visible' : 'hidden' }}
          >
            <PtySession sessionId={s.id} active={s.id === activeId} />
          </div>
        ))}
      </div>
    </div>
  )
}
