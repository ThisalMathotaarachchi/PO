import { api } from '../api/client'
import { languageForPath, usePoStore } from '../store'
import { useEffect, useRef, useState } from 'react'

type Mode = 'files' | 'code' | 'symbol'
type Result = { path: string; line?: number; preview?: string; kind: Mode }

interface Props { open: boolean; onClose: () => void }

export function FileSearch({ open, onClose }: Props) {
  const [q, setQ]             = useState('')
  const [mode, setMode]       = useState<Mode>('files')
  const [results, setResults] = useState<Result[]>([])
  const [loading, setLoading] = useState(false)
  const [cursor, setCursor]   = useState(0)
  const inputRef  = useRef<HTMLInputElement>(null)
  const openTab   = usePoStore((s) => s.openTab)
  const workspace = usePoStore((s) => s.workspace)

  useEffect(() => {
    if (open) {
      setQ(''); setResults([]); setCursor(0); setMode('files')
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [open])

  useEffect(() => {
    if (!q.trim() || !open) { setResults([]); return }
    const tid = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await api.search(q, mode)
        const entries: Result[] = []
        for (const m of res.matches) {
          if (typeof m === 'string') entries.push({ path: m, kind: mode })
          else entries.push({ path: m.path, line: m.line, preview: m.text, kind: mode })
        }
        setResults(entries.slice(0, 50)); setCursor(0)
      } catch { setResults([]) }
      finally { setLoading(false) }
    }, 200)
    return () => clearTimeout(tid)
  }, [q, mode, open])

  async function openResult(r: Result) {
    try {
      const file = await api.readFile(r.path)
      openTab({ path: r.path, content: file.content, original: file.content, dirty: false, language: languageForPath(r.path) })
    } catch { /* missing */ }
    onClose()
  }

  if (!open) return null

  const modes: { id: Mode; label: string }[] = [
    { id: 'files', label: 'Files' },
    { id: 'code',  label: 'Code' },
    { id: 'symbol', label: 'Symbols' },
  ]

  return (
    <div
      className="modal-backdrop fixed inset-0 z-[5000] flex items-start justify-center pt-16"
      onClick={onClose}
    >
      <div
        className="modal-surface"
        style={{ width: '100%', maxWidth: 560, zIndex: 5001, overflow: 'hidden' }}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose()
          if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, results.length - 1)) }
          if (e.key === 'ArrowUp')   { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
          if (e.key === 'Enter' && results[cursor]) void openResult(results[cursor])
        }}
      >
        {/* Mode tabs */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '10px 10px 0', borderBottom: '1px solid var(--color-border-2)' }}>
          {modes.map((m) => (
            <button
              key={m.id}
              type="button"
              style={{
                padding: '4px 10px', fontSize: 11, borderRadius: 20, border: 'none',
                background: mode === m.id ? 'var(--color-paper-3)' : 'none',
                color: mode === m.id ? 'var(--color-ink)' : 'var(--color-ink-4)',
                cursor: 'default', marginBottom: 6,
              }}
              onClick={() => setMode(m.id)}
            >
              {m.label}
            </button>
          ))}
          {workspace && (
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--color-ink-4)', paddingRight: 4, paddingBottom: 6 }}>
              {workspace.name}
            </span>
          )}
        </div>

        {/* Input */}
        <div style={{ padding: '8px 8px' }}>
          <input
            ref={inputRef}
            className="field"
            style={{ fontSize: 14, padding: '10px 14px', borderRadius: 8 }}
            placeholder={
              mode === 'files' ? 'Search file names…' :
              mode === 'code'  ? 'Search code content…' :
              'Search symbols…'
            }
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        {/* Results */}
        <div className="scrollbar-thin" style={{ maxHeight: 320, overflowY: 'auto' }}>
          {loading && <div style={{ padding: '12px 16px', fontSize: 12, color: 'var(--color-ink-3)' }}>Searching…</div>}
          {!loading && q.trim() && results.length === 0 && (
            <div style={{ padding: '12px 16px', fontSize: 12, color: 'var(--color-ink-3)' }}>No results for "{q}"</div>
          )}
          {results.map((r, i) => (
            <button
              key={`${r.path}-${r.line ?? i}`}
              type="button"
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                width: '100%', textAlign: 'left',
                padding: '8px 14px',
                background: i === cursor ? 'var(--color-paper-3)' : 'none',
                border: 'none', cursor: 'default',
              }}
              onClick={() => void openResult(r)}
              onMouseEnter={() => setCursor(i)}
            >
              <span style={{ flexShrink: 0, fontSize: 10, color: 'var(--color-ink-4)', marginTop: 2 }}>
                {r.kind === 'files' ? '·' : r.kind === 'symbol' ? 'ƒ' : '#'}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--color-ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.path}
                </div>
                {r.line !== undefined && (
                  <div style={{ fontSize: 10, color: 'var(--color-ink-4)' }}>Line {r.line}</div>
                )}
                {r.preview && (
                  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--color-ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.preview}
                  </div>
                )}
              </div>
            </button>
          ))}
        </div>

        <div style={{ borderTop: '1px solid var(--color-border-2)', padding: '6px 14px', fontSize: 10, color: 'var(--color-ink-4)' }}>
          ↑↓ navigate · Enter open · Esc close
        </div>
      </div>
    </div>
  )
}
