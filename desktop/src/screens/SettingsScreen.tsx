import { api } from '../api/client'
import type { AppSettings, ModelInfo } from '../api/client'
import { usePoStore } from '../store'
import { useEffect, useState } from 'react'

const TABS = ['General', 'AI / Models', 'Permissions', 'Workspace', 'Advanced'] as const

export function SettingsScreen() {
  const setScreen = usePoStore((s) => s.setScreen)
  const settings = usePoStore((s) => s.settings)
  const setSettings = usePoStore((s) => s.setSettings)
  const workspace = usePoStore((s) => s.workspace)
  const [tab, setTab] = useState<(typeof TABS)[number]>('General')
  const [draft, setDraft] = useState<AppSettings | null>(settings)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [diag, setDiag] = useState('')

  useEffect(() => {
    void (async () => {
      const s = await api.settings()
      setDraft(s)
      setSettings(s)
      const m = await api.models()
      setModels(m.models || [])
      setSelected(m.selected ?? null)
    })()
  }, [setSettings])

  async function save() {
    if (!draft) return
    const saved = await api.saveSettings(draft)
    setSettings(saved)
    setDraft(saved)
    setMsg('Saved')
    setTimeout(() => setMsg(null), 1500)
  }

  if (!draft) {
    return <div className="p-8 text-white/50">Loading settings…</div>
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col px-8 py-6" style={{ background: 'var(--color-paper)', color: 'var(--color-ink)' }}>
      <header className="mb-6 flex items-center justify-between">
        <div>
          <button type="button" className="text-xs text-white/40 hover:text-white/70" onClick={() => setScreen(workspace ? 'workspace' : 'home')}>
            ← Back
          </button>
          <h1 className="mt-2 text-2xl font-medium">Settings</h1>
        </div>
        <button type="button" className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black" onClick={() => void save()}>
          Save
        </button>
      </header>
      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded-full px-3 py-1.5 text-xs ${tab === t ? 'bg-white text-black' : 'border border-white/10 text-white/55'}`}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="glass scrollbar-thin flex-1 overflow-auto rounded-3xl p-6">
        {tab === 'General' && (
          <div className="space-y-4">
            <Field label="Appearance">
              <select
                className="field"
                value={draft.appearance}
                onChange={(e) => setDraft({ ...draft, appearance: e.target.value })}
              >
                <option value="dark">Dark</option>
                <option value="light">Light (coming soon)</option>
              </select>
            </Field>
            <Field label="Startup">
              <select className="field" value={draft.startup} onChange={(e) => setDraft({ ...draft, startup: e.target.value })}>
                <option value="home">Open Home</option>
                <option value="last">Restore last workspace</option>
              </select>
            </Field>
            <Toggle
              label="Notifications"
              checked={draft.notifications}
              onChange={(v) => setDraft({ ...draft, notifications: v })}
            />
            <p className="text-xs text-white/35">Shortcuts: Ctrl+P files · Ctrl+Shift+P palette · Ctrl+` terminal · Ctrl+S save · Esc close</p>
          </div>
        )}
        {tab === 'AI / Models' && (
          <div className="space-y-4">
            <Field label="Ollama host">
              <input className="field" value={draft.ollama_host} onChange={(e) => setDraft({ ...draft, ollama_host: e.target.value })} />
            </Field>
            <Toggle label="Automatic model routing" checked={draft.auto_route} onChange={(v) => setDraft({ ...draft, auto_route: v })} />
            <Field label="Preferred model (optional)">
              <select
                className="field"
                value={draft.preferred_model}
                onChange={(e) => setDraft({ ...draft, preferred_model: e.target.value })}
              >
                <option value="">Auto</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
                  </option>
                ))}
              </select>
            </Field>
            <div>
              <div className="mb-2 text-xs text-white/40">Installed models</div>
              <div className="space-y-2">
                {models.length === 0 ? (
                  <p className="text-sm text-white/45">No models discovered. Install a model in Ollama.</p>
                ) : (
                  models.map((m) => (
                    <div key={m.id} className="rounded-xl border border-white/10 px-3 py-2 text-sm">
                      <div className="font-medium">{m.name}{selected === m.id ? ' · selected' : ''}</div>
                      <div className="text-xs text-white/40">
                        {m.family || 'unknown'} · {(m.capabilities || []).join(', ')}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
        {tab === 'Permissions' && (
          <div className="space-y-4">
            <Field label="Permission mode">
              <select
                className="field"
                value={draft.permission_mode}
                onChange={(e) => setDraft({ ...draft, permission_mode: e.target.value })}
              >
                <option value="standard">Standard</option>
                <option value="strict">Strict</option>
              </select>
            </Field>
            <Toggle
              label="Auto-approve controlled (yellow) actions"
              checked={draft.auto_approve_yellow}
              onChange={(v) => setDraft({ ...draft, auto_approve_yellow: v })}
            />
            <p className="rounded-xl border border-white/10 bg-black/30 p-3 text-xs text-white/50">
              Po never places real-money trades, submits live orders, transfers funds, or bypasses trading safeguards.
            </p>
          </div>
        )}
        {tab === 'Workspace' && (
          <div className="space-y-4">
            <Field label="Default project location">
              <input
                className="field"
                value={draft.default_workspace}
                onChange={(e) => setDraft({ ...draft, default_workspace: e.target.value })}
                placeholder="D:\\Projects"
              />
            </Field>
            <Field label="Ignored directories (comma-separated)">
              <input
                className="field"
                value={draft.ignore_directories.join(', ')}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    ignore_directories: e.target.value
                      .split(',')
                      .map((x) => x.trim())
                      .filter(Boolean),
                  })
                }
              />
            </Field>
          </div>
        )}
        {tab === 'Advanced' && (
          <div className="space-y-4">
            <Field label="Log level">
              <select className="field" value={draft.log_level} onChange={(e) => setDraft({ ...draft, log_level: e.target.value })}>
                <option>INFO</option>
                <option>WARNING</option>
                <option>DEBUG</option>
                <option>ERROR</option>
              </select>
            </Field>
            <button
              type="button"
              className="rounded-full border border-white/15 px-3 py-1.5 text-xs"
              onClick={() =>
                void (async () => {
                  try {
                    const h = await api.health()
                    const m = await api.models()
                    setDiag(JSON.stringify({ health: h, models: m }, null, 2))
                  } catch (err) {
                    setDiag(String(err))
                  }
                })()
              }
            >
              Run diagnostics
            </button>
            {diag ? (
              <pre className="scrollbar-thin max-h-64 overflow-auto rounded-xl bg-black/50 p-3 font-mono text-[11px] text-white/60">
                {diag}
              </pre>
            ) : null}
          </div>
        )}
        {msg ? <p className="mt-4 text-xs text-white/50">{msg}</p> : null}
      </div>
      <style>{`.field{width:100%;border-radius:0.75rem;border:1px solid rgba(255,255,255,0.1);background:rgba(0,0,0,0.4);padding:0.5rem 0.75rem;outline:none}`}</style>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1 text-xs text-white/40">{label}</div>
      {children}
    </label>
  )
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" className="flex w-full items-center justify-between rounded-xl border border-white/10 px-3 py-2 text-sm" onClick={() => onChange(!checked)}>
      <span>{label}</span>
      <span className={`h-5 w-9 rounded-full p-0.5 ${checked ? 'bg-white' : 'bg-white/20'}`}>
        <span className={`block h-4 w-4 rounded-full transition ${checked ? 'translate-x-4 bg-black' : 'bg-white/80'}`} />
      </span>
    </button>
  )
}
