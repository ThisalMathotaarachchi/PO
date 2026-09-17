import { api } from '../api/client'
import type { FileChange } from '../api/client'
import { useEffect, useState } from 'react'

function DiffLines({ diff }: { diff: string }) {
  if (!diff) return (
    <p style={{ padding: '6px 12px', fontSize: 11, color: 'var(--color-ink-4)', fontFamily: 'var(--font-mono)' }}>
      No diff available.
    </p>
  )
  const lines = diff.split('\n')
  return (
    <div style={{ overflowX: 'auto' }}>
      <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.7, margin: 0 }}>
        {lines.map((line, i) => {
          let color = 'var(--color-ink-3)'
          let bg = 'transparent'
          if (line.startsWith('+++') || line.startsWith('---')) {
            color = 'var(--color-ink-3)'
          } else if (line.startsWith('@@')) {
            color = 'var(--color-ink-4)'
            bg = 'var(--color-paper-2)'
          } else if (line.startsWith('+')) {
            color = '#4A7A4A'
            bg = 'rgba(74,122,74,0.07)'
          } else if (line.startsWith('-')) {
            color = '#9A5A4A'
            bg = 'rgba(154,90,74,0.06)'
          }
          return (
            <div key={i} style={{ background: bg, padding: '0 12px' }}>
              <span style={{ color }}>{line || ' '}</span>
            </div>
          )
        })}
      </pre>
    </div>
  )
}

function FileCard({ change, idx }: { change: FileChange; idx: number }) {
  const [expanded, setExpanded] = useState(idx === 0)
  const addCount = (change.diff.match(/^\+[^+]/gm) || []).length
  const delCount = (change.diff.match(/^-[^-]/gm) || []).length

  return (
    <div style={{
      overflow: 'hidden',
      borderRadius: 8,
      border: '1px solid var(--color-border)',
      background: 'var(--color-paper)',
      marginBottom: 8,
    }}>
      <button
        type="button"
        style={{
          display: 'flex', alignItems: 'center', gap: 10,
          width: '100%', textAlign: 'left',
          padding: '10px 14px',
          background: 'none', border: 'none',
          cursor: 'default',
        }}
        onClick={() => setExpanded((v) => !v)}
      >
        <span style={{ width: 14, fontSize: 10, color: 'var(--color-ink-4)', flexShrink: 0 }}>
          {expanded ? '▾' : '▸'}
        </span>
        <span style={{ flex: 1, fontSize: 13, fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--color-ink)' }}>
          {change.path}
        </span>
        <span style={{ flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
          {addCount > 0 && <span style={{ color: '#4A7A4A' }}>+{addCount}</span>}
          {addCount > 0 && delCount > 0 && <span style={{ color: 'var(--color-ink-4)', margin: '0 3px' }}>/</span>}
          {delCount > 0 && <span style={{ color: '#9A5A4A' }}>−{delCount}</span>}
        </span>
      </button>
      {expanded && (
        <div style={{ borderTop: '1px solid var(--color-border)' }}>
          <DiffLines diff={change.diff} />
        </div>
      )}
    </div>
  )
}

export function DiffReview({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [changes, setChanges] = useState<FileChange[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    void api.changes().then((r) => setChanges(r.changes)).finally(() => setLoading(false))
  }, [open])

  if (!open) return null

  const totalAdded   = changes.reduce((n, c) => n + (c.diff.match(/^\+[^+]/gm) || []).length, 0)
  const totalRemoved = changes.reduce((n, c) => n + (c.diff.match(/^-[^-]/gm) || []).length, 0)

  return (
    <div
      className="modal-backdrop fixed inset-0 z-[5000] flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="modal-surface flex flex-col"
        style={{ maxHeight: '85vh', width: '100%', maxWidth: 800, zIndex: 5001 }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          borderBottom: '1px solid var(--color-border)',
          padding: '14px 20px',
          flexShrink: 0,
        }}>
          <div>
            <h2 style={{ fontSize: 15, fontWeight: 500, color: 'var(--color-ink)', margin: 0 }}>
              Pending Changes
            </h2>
            {changes.length > 0 && (
              <p style={{ fontSize: 12, color: 'var(--color-ink-3)', marginTop: 2 }}>
                {changes.length} file{changes.length !== 1 ? 's' : ''} ·{' '}
                <span style={{ color: '#4A7A4A' }}>+{totalAdded}</span>
                {' / '}
                <span style={{ color: '#9A5A4A' }}>−{totalRemoved}</span>
              </p>
            )}
          </div>
          <button type="button" className="btn-ghost" style={{ padding: '4px 12px', fontSize: 12 }} onClick={onClose}>
            Close
          </button>
        </div>

        {/* Body */}
        <div className="scrollbar-thin" style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
          {loading && <p style={{ textAlign: 'center', fontSize: 13, color: 'var(--color-ink-3)' }}>Loading changes…</p>}
          {!loading && changes.length === 0 && (
            <p style={{ textAlign: 'center', fontSize: 13, color: 'var(--color-ink-3)', padding: '32px 0' }}>
              No pending file changes.
            </p>
          )}
          {changes.map((c, i) => <FileCard key={c.path} change={c} idx={i} />)}
        </div>

        {changes.length > 0 && (
          <div style={{ borderTop: '1px solid var(--color-border)', padding: '10px 20px', flexShrink: 0 }}>
            <span style={{ fontSize: 11, color: 'var(--color-ink-4)' }}>
              These changes were made by Po during the current session.
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
