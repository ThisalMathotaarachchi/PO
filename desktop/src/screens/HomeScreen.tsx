import { api } from '../api/client'
import { PoMark } from '../components/PoMark'
import { usePoStore } from '../store'
import { useMemo, useState } from 'react'

const SUGGESTIONS = ['Fix a bug', 'Build a feature', 'Explain this project', 'Run the tests', 'Refactor this code']

function formatLastOpened(iso: string): string {
  try {
    const d = new Date(iso)
    const now = new Date()
    if (d.toDateString() === now.toDateString()) return 'Last opened today'
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    if (d.toDateString() === yesterday.toDateString()) return 'Last opened yesterday'
    return `Last opened ${d.toLocaleDateString()}`
  } catch { return 'Last opened recently' }
}

export function HomeScreen() {
  const projects       = usePoStore((s) => s.projects)
  const promptDraft    = usePoStore((s) => s.promptDraft)
  const setPromptDraft = usePoStore((s) => s.setPromptDraft)
  const setScreen      = usePoStore((s) => s.setScreen)
  const setWorkspace   = usePoStore((s) => s.setWorkspace)
  const setProjects    = usePoStore((s) => s.setProjects)
  const setPendingAsk  = usePoStore((s) => s.setPendingAsk)
  const [busy, setBusy]         = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName]         = useState('')
  const [description, setDescription] = useState('')
  const [location, setLocation] = useState('')

  const sorted = useMemo(() => [...projects], [projects])

  async function refreshProjects() {
    const res = await api.projects()
    setProjects(res.projects)
  }

  async function openPath(path: string, projectName?: string) {
    setBusy(true); setError(null)
    try {
      const ws = await api.openWorkspace(path, projectName)
      setWorkspace(ws)
      await refreshProjects()
      if (promptDraft.trim()) setPendingAsk(promptDraft.trim())
      setScreen('workspace')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open project')
    } finally { setBusy(false) }
  }

  async function browse() {
    try {
      const { path } = await api.pickFolder()
      if (path) { setLocation(path); if (!name) setName(path.split(/[/\\]/).filter(Boolean).pop() || '') }
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not browse folders') }
  }

  async function createProject() {
    if (!location.trim() || !name.trim()) { setError('Name and location are required.'); return }
    setBusy(true); setError(null)
    try {
      const path = location.replace(/[/\\]$/, '') + (location.endsWith(name) ? '' : `\\${name}`)
      const ws = await api.createWorkspace(path, name)
      if (description.trim()) await api.writeFile('README.md', `# ${name}\n\n${description}\n`).catch(() => undefined)
      setWorkspace(ws)
      await refreshProjects()
      setShowCreate(false)
      setScreen('workspace')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create project')
    } finally { setBusy(false) }
  }

  async function openExisting() {
    try {
      const { path } = await api.pickFolder()
      if (path) await openPath(path)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not open project') }
  }

  return (
    <div
      className="fade-in"
      style={{
        height: '100%', width: '100%', display: 'flex', flexDirection: 'column',
        background: 'var(--color-paper)',
        position: 'relative',
      }}
    >
      {/* Paper rules behind content */}
      <div className="ruled-paper" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', opacity: 0.5 }} />

      <div style={{
        position: 'relative', zIndex: 1,
        maxWidth: 640, width: '100%',
        margin: '0 auto', padding: '40px 24px',
        display: 'flex', flexDirection: 'column', height: '100%',
      }}>
        {/* Header */}
        <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 48 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <PoMark size={28} color="#1C1917" />
            <span style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', fontSize: 22, color: 'var(--color-ink)' }}>
              Po
            </span>
          </div>
          <button
            type="button"
            className="btn-ghost"
            style={{ fontSize: 12, padding: '5px 14px' }}
            onClick={() => setScreen('settings')}
          >
            Settings
          </button>
        </header>

        {/* Main */}
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <h1 style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', fontSize: 32, color: 'var(--color-ink)', marginBottom: 6, textAlign: 'center' }}>
            Welcome back
          </h1>
          <p style={{ fontSize: 14, color: 'var(--color-ink-3)', marginBottom: 32 }}>What are we building?</p>

          {/* Prompt input */}
          <div style={{
            width: '100%',
            background: 'var(--color-paper)',
            border: '1px solid var(--color-border)',
            borderRadius: 12,
            padding: 8,
            boxShadow: '0 2px 8px rgba(28,25,23,0.07)',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10,
              background: 'var(--color-paper-2)', borderRadius: 8, padding: '10px 14px',
            }}>
              <PoMark size={20} color="#78716C" />
              <input
                style={{
                  flex: 1, background: 'none', border: 'none', outline: 'none',
                  fontSize: 14, color: 'var(--color-ink)',
                  fontFamily: 'var(--font-sans)',
                }}
                placeholder="What should we work on?"
                value={promptDraft}
                onChange={(e) => setPromptDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && sorted[0]) void openPath(sorted[0].path) }}
              />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '8px 6px 4px' }}>
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  style={{
                    padding: '3px 10px', fontSize: 12, borderRadius: 20,
                    border: '1px solid var(--color-border)',
                    background: 'none', color: 'var(--color-ink-3)',
                    cursor: 'default',
                  }}
                  onClick={() => setPromptDraft(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Projects */}
          <div style={{ width: '100%', marginTop: 40 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <span style={{ fontSize: 10, letterSpacing: '0.15em', color: 'var(--color-ink-4)', fontWeight: 500 }}>MY PROJECTS</span>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" className="btn-ghost" style={{ fontSize: 12, padding: '4px 12px' }} onClick={() => setShowCreate(true)}>New</button>
                <button type="button" className="btn-ghost" style={{ fontSize: 12, padding: '4px 12px' }} onClick={() => void openExisting()}>Open</button>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {sorted.length === 0 ? (
                <div style={{
                  padding: '24px 20px', textAlign: 'center', fontSize: 13,
                  color: 'var(--color-ink-4)', fontStyle: 'italic',
                  border: '1px dashed var(--color-border)', borderRadius: 10,
                }}>
                  No projects yet. Create or open one to begin.
                </div>
              ) : sorted.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  disabled={busy}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    padding: '14px 18px', borderRadius: 10,
                    border: '1px solid var(--color-border)',
                    background: 'var(--color-paper)',
                    cursor: 'default',
                    boxShadow: '0 1px 3px rgba(28,25,23,0.05)',
                  }}
                  onClick={() => void openPath(p.path, p.name)}
                >
                  <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-ink)' }}>{p.name}</div>
                  <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--color-ink-3)', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.path}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-ink-4)', marginTop: 6 }}>{formatLastOpened(p.last_opened)}</div>
                </button>
              ))}
            </div>
          </div>
          {error && <p style={{ marginTop: 16, fontSize: 13, color: '#9A5A4A' }}>{error}</p>}
        </main>
      </div>

      {/* Create project modal */}
      {showCreate && (
        <div
          className="modal-backdrop fixed inset-0 z-[5000] flex items-center justify-center p-6"
          onClick={() => setShowCreate(false)}
        >
          <div
            className="modal-surface"
            style={{ width: '100%', maxWidth: 480, padding: 28, zIndex: 5001 }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2 style={{ fontSize: 16, fontWeight: 500, color: 'var(--color-ink)', marginBottom: 20 }}>Create Project</h2>
            <label style={{ display: 'block', fontSize: 11, color: 'var(--color-ink-3)', marginBottom: 4 }}>Project name</label>
            <input className="field" style={{ marginBottom: 14 }} value={name} onChange={(e) => setName(e.target.value)} />
            <label style={{ display: 'block', fontSize: 11, color: 'var(--color-ink-3)', marginBottom: 4 }}>Description (optional)</label>
            <textarea className="field" style={{ marginBottom: 14, minHeight: 64, resize: 'vertical' }} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            <label style={{ display: 'block', fontSize: 11, color: 'var(--color-ink-3)', marginBottom: 4 }}>Location</label>
            <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
              <input className="field" style={{ flex: 1 }} value={location} onChange={(e) => setLocation(e.target.value)} placeholder="D:\\Projects" />
              <button type="button" className="btn-ghost" style={{ flexShrink: 0 }} onClick={() => void browse()}>Browse</button>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" className="btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
              <button type="button" className="btn-primary" disabled={busy} onClick={() => void createProject()}>Create Project</button>
            </div>
            <div style={{ marginTop: 12, textAlign: 'center' }}>
              <button type="button" style={{ fontSize: 12, color: 'var(--color-ink-3)', background: 'none', border: 'none', cursor: 'default' }} onClick={() => void openExisting()}>
                Or open an existing project →
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
