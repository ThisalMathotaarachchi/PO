import { api } from '../api/client'
import { PoMarkAnimated } from '../components/PoMark'
import { usePoStore } from '../store'
import { useCallback, useEffect } from 'react'

export function LaunchScreen() {
  const bootError    = usePoStore((s) => s.bootError)
  const setBootError = usePoStore((s) => s.setBootError)
  const setScreen    = usePoStore((s) => s.setScreen)
  const setProjects  = usePoStore((s) => s.setProjects)
  const setSettings  = usePoStore((s) => s.setSettings)
  const setWorkspace = usePoStore((s) => s.setWorkspace)

  const boot = useCallback(async () => {
    setBootError(null)
    try {
      const health = await api.health()
      if (!health.ok) throw new Error('Po services are unavailable.')
      if (!health.ollama?.ok) throw new Error("Po couldn't connect to Ollama.")
      const [projects, appSettings] = await Promise.all([api.projects(), api.settings()])
      setProjects(projects.projects)
      setSettings(appSettings)
      try { setWorkspace(await api.activeWorkspace()) } catch { setWorkspace(null) }
      await new Promise((r) => setTimeout(r, 800))
      if ((appSettings.startup || 'home') === 'last') {
        try { setWorkspace(await api.activeWorkspace()); setScreen('workspace'); return } catch { /* fall through */ }
      }
      setScreen('home')
    } catch (err) {
      setBootError(err instanceof Error ? err.message : "Po couldn't start correctly.")
    }
  }, [setBootError, setProjects, setScreen, setSettings, setWorkspace])

  useEffect(() => { void boot() }, [boot])

  return (
    <div
      className="fade-in"
      style={{
        height: '100%', width: '100%',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--color-paper)',
        position: 'relative',
      }}
    >
      {/* Subtle ruled lines behind */}
      <div className="ruled-paper" style={{ position: 'absolute', inset: 0, opacity: 0.4, pointerEvents: 'none' }} />

      <div style={{ position: 'relative', zIndex: 1, textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
        <PoMarkAnimated size={80} state={bootError ? 'error' : 'idle'} />

        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', fontSize: 36, color: 'var(--color-ink)', letterSpacing: '-0.01em' }}>
            Po
          </div>
          <div style={{ fontSize: 13, color: 'var(--color-ink-3)', marginTop: 4 }}>
            Your trusted coding assistant
          </div>
        </div>

        {bootError ? (
          <div style={{
            marginTop: 8, maxWidth: 400, width: '100%',
            background: 'var(--color-paper)',
            border: '1px solid var(--color-border)',
            borderRadius: 12,
            padding: '20px 24px',
            boxShadow: '0 2px 12px rgba(28,25,23,0.08)',
          }}>
            <p style={{ fontSize: 14, color: 'var(--color-ink)', marginBottom: 6 }}>Po couldn't start correctly.</p>
            <p style={{ fontSize: 12, color: 'var(--color-ink-3)', marginBottom: 16 }}>{bootError}</p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 10 }}>
              <button type="button" className="btn-primary" style={{ fontSize: 13, padding: '7px 20px' }} onClick={() => void boot()}>
                Retry
              </button>
              <button type="button" className="btn-ghost" style={{ fontSize: 13, padding: '7px 20px' }} onClick={() => setScreen('settings')}>
                Settings
              </button>
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 12, color: 'var(--color-ink-4)', letterSpacing: '0.05em', animation: 'status-pulse 2s ease-in-out infinite' }}>
            Starting workspace…
          </div>
        )}
      </div>
    </div>
  )
}
