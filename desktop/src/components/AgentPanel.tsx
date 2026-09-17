/**
 * AgentPanel — Po's conversation + task control area.
 *
 * Layout (bottom of workspace):
 *   ┌─────────────────────────────────────────────────────┐
 *   │ [conversation feed — all turns, oldest first]       │
 *   │   USER  "Create index.html…"                  ───── │
 *   │   PO    Reading project…                      ───── │
 *   │         ✓ Created index.html.                       │
 *   │         Activity · 4 actions ▸                      │
 *   │   USER  "Add a paragraph…"                    ───── │
 *   │   PO    Making changes…                             │
 *   ├─────────────────────────────────────────────────────┤
 *   │ [input row]  📎  [ What should we work on? ]  [GO]  │
 *   └─────────────────────────────────────────────────────┘
 */

import { api } from '../api/client'
import { PoMarkAnimated } from './PoMark'
import { usePoStore } from '../store'
import type { ConversationTurn } from '../store'
import { useEffect, useRef, useState } from 'react'

// ─── Status messages ────────────────────────────────────────────────────────

function statusMessage(s: string): string {
  switch (s) {
    case 'UNDERSTANDING':        return 'Reading the project…'
    case 'EXPLORING':            return 'Exploring files…'
    case 'PLANNING':             return 'Forming a plan…'
    case 'EXECUTING':            return 'Making changes…'
    case 'TESTING':              return 'Running tests…'
    case 'DEBUGGING':            return 'Debugging…'
    case 'VERIFYING':            return 'Verifying…'
    case 'WAITING_FOR_APPROVAL': return 'Waiting for your approval…'
    case 'ERROR':                return 'Something went wrong.'
    case 'CANCELLED':            return 'Cancelled.'
    default:                     return ''
  }
}

// ─── Activity collapsible ────────────────────────────────────────────────────

function ActivityLog({ turn }: { turn: ConversationTurn }) {
  const [open, setOpen] = useState(false)
  const count = turn.activity.length
  if (count === 0) return null
  const items = turn.outcome !== 'pending' ? turn.activity.slice(0, -1) : turn.activity
  if (items.length === 0) return null

  return (
    <div style={{ marginTop: 6 }}>
      <button
        type="button"
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontSize: 11, color: 'var(--color-ink-4)',
          background: 'none', border: 'none',
          cursor: 'default', padding: 0,
        }}
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ fontFamily: 'var(--font-mono)' }}>{open ? '▾' : '▸'}</span>
        <span>Activity · {items.length} action{items.length !== 1 ? 's' : ''}</span>
      </button>
      {open && (
        <div style={{
          marginTop: 4,
          paddingLeft: 12,
          borderLeft: '1px solid var(--color-border)',
        }}>
          {items.map((a) => {
            let prefix = ''
            const clr = a.kind === 'success' ? 'var(--color-ink-2)' :
                        a.kind === 'error'   ? 'var(--color-ink-3)' :
                        a.kind === 'command' ? 'var(--color-ink-3)' :
                        'var(--color-ink-3)'
            if (a.kind === 'success') prefix = '✓ '
            else if (a.kind === 'error') prefix = '✗ '
            else if (a.kind === 'command') prefix = '$ '
            return (
              <div key={a.id} style={{
                fontSize: 11, lineHeight: 1.6,
                fontFamily: a.kind === 'command' ? 'var(--font-mono)' : 'inherit',
                color: clr,
              }}>
                {prefix}{a.text}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── Completion result card ──────────────────────────────────────────────────

function CompletionCard({ turn, onOpenFile }: { turn: ConversationTurn; onOpenFile: (p: string) => void }) {
  const isError     = turn.outcome === 'error'
  const isCancelled = turn.outcome === 'cancelled'
  const icon        = isError ? '✗' : isCancelled ? '○' : '✓'
  const label       = isError ? turn.summary : isCancelled ? 'Cancelled.' : (turn.summary || 'Done.')

  return (
    <div style={{
      marginTop: 6,
      borderRadius: 8,
      border: `1px solid ${isError ? 'var(--color-ink-4)' : 'var(--color-border)'}`,
      background: isError ? 'rgba(192,118,90,0.05)' : 'var(--color-paper-2)',
      padding: '8px 10px',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        fontSize: 12, fontWeight: 500,
        color: isError ? 'var(--color-ink-3)' : 'var(--color-ink)',
      }}>
        <span>{icon}</span>
        <span>{label}</span>
      </div>
      {!isError && !isCancelled && turn.changedPaths.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {turn.changedPaths.map((p) => (
            <button
              key={p}
              type="button"
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                width: '100%', textAlign: 'left',
                padding: '2px 4px', borderRadius: 4,
                fontSize: 11, fontFamily: 'var(--font-mono)',
                color: 'var(--color-ink-3)',
                background: 'none', border: 'none',
                cursor: 'default',
              }}
              onClick={() => onOpenFile(p)}
            >
              <span style={{ color: 'var(--color-ink-4)' }}>·</span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {p.split(/[/\\]/).pop()}
              </span>
              <span style={{ fontSize: 10, color: 'var(--color-ink-4)' }}>↗</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Single conversation turn ────────────────────────────────────────────────

function TurnView({
  turn,
  isActive,
  agentStatus,
  onOpenFile,
}: {
  turn: ConversationTurn
  isActive: boolean
  agentStatus: string
  onOpenFile: (p: string) => void
}) {
  // Live status message for the active turn
  const liveMsg = isActive ? statusMessage(agentStatus) : ''
  // Summary to show for an in-progress turn before it completes
  const lastActivity = turn.activity[turn.activity.length - 1]

  return (
    <div className="space-y-2">
      {/* User message — right aligned */}
      <div className="flex justify-end">
        <div style={{
          maxWidth: '78%',
          background: 'var(--color-paper-3)',
          border: '1px solid var(--color-border)',
          borderRadius: '12px 12px 4px 12px',
          padding: '8px 12px',
          fontSize: 13,
          lineHeight: 1.45,
          color: 'var(--color-ink)',
        }}>
          {turn.userPrompt}
        </div>
      </div>

      {/* Po response — left aligned */}
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5 shrink-0">
          <PoMarkAnimated
            size={20}
            state={isActive
              ? (agentStatus === 'ERROR' ? 'error'
                : agentStatus === 'EXECUTING' || agentStatus === 'TESTING' || agentStatus === 'DEBUGGING' ? 'working'
                : 'idle')
              : 'idle'
            }
          />
        </div>
        <div className="min-w-0 flex-1">
          {/* Live status while working */}
          {isActive && liveMsg && (
            <div style={{ fontSize: 12, color: 'var(--color-ink-3)', fontStyle: 'italic' }}>{liveMsg}</div>
          )}
          {isActive && !liveMsg && lastActivity && (
            <div style={{ fontSize: 12, color: 'var(--color-ink-3)', fontStyle: 'italic' }}>{lastActivity.text}</div>
          )}
          {turn.outcome !== 'pending' && (
            <CompletionCard turn={turn} onOpenFile={onOpenFile} />
          )}
          <ActivityLog turn={turn} />
        </div>
      </div>
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────────────────

export function AgentPanel({
  onSubmit,
  onOpenFile,
}: {
  onSubmit: (prompt: string) => Promise<void>
  onOpenFile: (path: string) => void
}) {
  const conversation  = usePoStore((s) => s.conversation)
  const activeTurnId  = usePoStore((s) => s.activeTurnId)
  const agentStatus   = usePoStore((s) => s.agentStatus)
  const status        = usePoStore((s) => s.status)
  const task          = usePoStore((s) => s.task)
  const approval      = usePoStore((s) => s.approval)
  const setApproval   = usePoStore((s) => s.setApproval)
  const promptDraft   = usePoStore((s) => s.promptDraft)
  const setPromptDraft = usePoStore((s) => s.setPromptDraft)
  const [busy, setBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const feedRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const isWorking  = status === 'working' || status === 'waiting'
  const isIdle     = !isWorking && conversation.length === 0
  const activeTask = task && (status === 'working' || status === 'waiting')

  // Auto-scroll conversation to bottom on new turns / activity
  useEffect(() => {
    const el = feedRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [conversation.length, activeTurnId])

  // Also scroll when the active turn gains new activity
  const activeTurn = activeTurnId
    ? conversation.find((t) => t.id === activeTurnId)
    : null
  const activeTurnActivityLen = activeTurn?.activity.length ?? 0
  useEffect(() => {
    const el = feedRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [activeTurnActivityLen])

  async function send() {
    const text = promptDraft.trim()
    if (!text || busy || isWorking) return
    setBusy(true)
    try {
      await onSubmit(text)
      setPromptDraft('')
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (!task || cancelling) return
    setCancelling(true)
    try {
      await api.cancelTask(task.id)
    } finally {
      // Backend will emit TASK_CANCELLED which resets status
      setCancelling(false)
    }
  }

  return (
    <div className="flex h-full flex-col" style={{ background: 'var(--color-paper)' }}>

      {/* ── Conversation feed ── */}
      <div
        ref={feedRef}
        className="scrollbar-thin min-h-0 flex-1 space-y-4 overflow-auto px-4 py-3 ruled-paper"
      >
        {conversation.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-4">
            <PoMarkAnimated size={52} state="idle" />
            <div style={{ textAlign: 'center' }}>
              <p style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', fontSize: 20, color: 'var(--color-ink)', marginBottom: 4 }}>
                Po
              </p>
              <p style={{ fontSize: 13, color: 'var(--color-ink-3)' }}>
                What should we work on?
              </p>
            </div>
          </div>
        )}
        {conversation.map((turn) => (
          <TurnView
            key={turn.id}
            turn={turn}
            isActive={turn.id === activeTurnId}
            agentStatus={agentStatus}
            onOpenFile={onOpenFile}
          />
        ))}
      </div>

      {/* ── Approval request ── */}
      {approval && (
        <div style={{
          margin: '0 12px 8px',
          borderRadius: 8,
          border: `1px solid ${approval.level === 'red' ? 'var(--color-ink-3)' : 'var(--color-border)'}`,
          background: approval.level === 'red' ? 'rgba(192,118,90,0.06)' : 'var(--color-paper-2)',
          padding: '12px',
          flexShrink: 0,
        }}>
          <div style={{ fontSize: 12, color: 'var(--color-ink-2)', marginBottom: 6 }}>
            {approval.level === 'red' ? '⚠ Destructive · ' : ''}Po wants to run:
          </div>
          <pre style={{
            background: 'var(--color-paper-3)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            padding: '6px 10px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--color-ink)',
            overflow: 'auto',
          }}>
            {approval.command || approval.tool || approval.message}
          </pre>
          {approval.message && (approval.command || approval.tool) && (
            <p style={{ fontSize: 11, color: 'var(--color-ink-3)', marginTop: 4 }}>{approval.message}</p>
          )}
          <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="btn-primary"
              style={{ padding: '4px 14px', fontSize: 12 }}
              onClick={() => void api.approveTask(approval.taskId, true).then(() => setApproval(null))}
            >
              Allow
            </button>
            <button
              type="button"
              className="btn-ghost"
              style={{ padding: '4px 14px', fontSize: 12 }}
              onClick={() => void api.approveTask(approval.taskId, false).then(() => setApproval(null))}
            >
              Deny
            </button>
          </div>
        </div>
      )}

      {/* ── Composer row ── */}
      <div className="ruled-paper"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          borderTop: '1px solid var(--color-border)',
          padding: '8px 12px',
          flexShrink: 0,
          background: 'var(--color-paper)',
        }}
      >
        {/* Attachment */}
        <button
          type="button"
          title="Attach file (coming soon — requires vision model)"
          style={{
            flexShrink: 0, width: 30, height: 30,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            background: 'none',
            color: 'var(--color-ink-4)',
            cursor: 'default',
          }}
          onClick={() => alert('File attachments will be available when a vision-capable model is installed.')}
        >
          <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden>
            <path d="M7 1v8M4 6l3 3 3-3M1 11h12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>

        {/* Text input — ruled-paper feel, no visible box */}
        <input
          ref={inputRef}
          className="input-paper"
          style={{ flex: 1 }}
          placeholder={isIdle ? 'What should we work on?' : 'Follow up…'}
          value={promptDraft}
          disabled={isWorking}
          onChange={(e) => setPromptDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() }
          }}
        />

        {/* Go / Stop */}
        {activeTask ? (
          <button
            type="button"
            disabled={cancelling}
            title="Stop task"
            style={{
              flexShrink: 0, width: 32, height: 32,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--color-ink)',
              border: 'none', borderRadius: 6,
              color: 'var(--color-paper)',
              cursor: 'default', opacity: cancelling ? 0.5 : 1,
            }}
            onClick={() => void cancel()}
          >
            <svg width="11" height="11" viewBox="0 0 11 11" fill="currentColor" aria-hidden>
              <rect x="1" y="1" width="9" height="9" rx="1.5"/>
            </svg>
          </button>
        ) : (
          <button
            type="button"
            disabled={busy || !promptDraft.trim()}
            className="btn-primary"
            style={{ flexShrink: 0, padding: '7px 16px', fontSize: 13 }}
            onClick={() => void send()}
          >
            Go
          </button>
        )}
      </div>
    </div>
  )
}
