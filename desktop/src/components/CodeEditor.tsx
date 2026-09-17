import Editor, { type BeforeMount } from '@monaco-editor/react'
import { api } from '../api/client'
import { usePoStore } from '../store'
import { useEffect } from 'react'

// Register a custom Monaco theme that matches the paper design.
// The defineTheme call is idempotent — safe to call on every mount.
const handleBeforeMount: BeforeMount = (monaco) => {
  monaco.editor.defineTheme('po-paper', {
    base: 'vs',
    inherit: true,
    rules: [
      // Make all default token colours slightly warmer/inkier
      { token: '', foreground: '1C1917', background: 'F3F0E8' },
      { token: 'comment', foreground: 'A8A29E', fontStyle: 'italic' },
      { token: 'string', foreground: '5A6E3A' },
      { token: 'keyword', foreground: '44403C', fontStyle: 'bold' },
      { token: 'number', foreground: '78452A' },
      { token: 'type', foreground: '3A5A6E' },
    ],
    colors: {
      'editor.background':                 '#F3F0E8',
      'editor.foreground':                 '#1C1917',
      'editorLineNumber.foreground':       '#C8C2B4',
      'editorLineNumber.activeForeground': '#78716C',
      'editor.lineHighlightBackground':    '#EDE9DF',
      'editor.selectionBackground':        '#D6D0C4',
      'editor.inactiveSelectionBackground':'#E4DFD3',
      'editorCursor.foreground':           '#1C1917',
      'editorWhitespace.foreground':       '#DDD8CE',
      'editorIndentGuide.background1':     '#DDD8CE',
      'editorIndentGuide.activeBackground1':'#C8C2B4',
      'editor.findMatchBackground':        '#C4A86A44',
      'editor.findMatchHighlightBackground':'#C4A86A22',
      'scrollbar.shadow':                  '#00000010',
      'scrollbarSlider.background':        '#C8C2B455',
      'scrollbarSlider.hoverBackground':   '#C8C2B488',
      'scrollbarSlider.activeBackground':  '#78716C88',
      'minimap.background':                '#EDE9DF',
    },
  })
}

export function CodeEditor() {
  const tabs = usePoStore((s) => s.tabs)
  const activePath = usePoStore((s) => s.activePath)
  const setActivePath = usePoStore((s) => s.setActivePath)
  const updateTab = usePoStore((s) => s.updateTab)
  const closeTab = usePoStore((s) => s.closeTab)
  const explorerRefresh = usePoStore((s) => s.explorerRefresh)
  const active = tabs.find((t) => t.path === activePath) ?? null

  useEffect(() => {
    if (!activePath) return
    void (async () => {
      try {
        const file = await api.readFile(activePath)
        const tab = usePoStore.getState().tabs.find((t) => t.path === activePath)
        if (tab && !tab.dirty) {
          updateTab(activePath, { content: file.content, original: file.content, dirty: false, stale: false })
        }
      } catch {
        /* file may have been deleted */
      }
    })()
    // Re-run when explorer refreshes (catches FILE_CHANGED for active tab)
    // or when active path changes (reloads stale tabs on switch)
  }, [explorerRefresh, activePath, updateTab])

  async function save() {
    if (!active) return
    await api.writeFile(active.path, active.content)
    updateTab(active.path, { original: active.content, dirty: false })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        void save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // active is the correct dep — we need the latest tab content when Ctrl+S fires
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  if (!tabs.length) {
    return (
      <div
        className="flex h-full flex-col items-center justify-center gap-6 ruled-paper"
        style={{ background: 'var(--color-paper)' }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, opacity: 0.6 }}>
          <svg width="64" height="64" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
            {/* PoMark inline for empty state */}
            <circle cx="24" cy="26" r="21" stroke="#1C1917" strokeWidth="1.2" strokeOpacity="0.18" fill="none"/>
            <ellipse cx="11" cy="9" rx="5.5" ry="6.5" fill="#1C1917"/>
            <ellipse cx="37" cy="9" rx="5.5" ry="6.5" fill="#1C1917"/>
            <circle cx="24" cy="26" r="18" fill="#1C1917" fillOpacity="0.04" stroke="#1C1917" strokeWidth="1.4"/>
            <ellipse cx="17" cy="23" rx="6" ry="7.5" fill="#1C1917" transform="rotate(-10 17 23)"/>
            <ellipse cx="31" cy="23" rx="6" ry="7.5" fill="#1C1917" transform="rotate(10 31 23)"/>
            <circle cx="17" cy="22" r="1.4" fill="white"/>
            <circle cx="31" cy="22" r="1.4" fill="white"/>
            <ellipse cx="24" cy="30" rx="1.8" ry="1.2" fill="#1C1917" fillOpacity="0.4"/>
            <path d="M 20 33 Q 24 36 28 33" stroke="#1C1917" strokeWidth="1.3" strokeLinecap="round" fill="none" strokeOpacity="0.5"/>
          </svg>
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', fontSize: 22, color: 'var(--color-ink)', marginBottom: 6 }}>
              Your workspace is ready.
            </p>
            <p style={{ fontSize: 13, color: 'var(--color-ink-3)' }}>
              Open a file from the Explorer, or ask Po what to build.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col ruled-paper" style={{ background: 'var(--color-paper)' }}>
      <div
        className="flex gap-0 overflow-x-auto"
        style={{ borderBottom: '1px solid var(--color-border)', background: 'var(--color-paper)', minHeight: 32, flexShrink: 0 }}
      >
        {tabs.map((t) => (
          <button
            key={t.path}
            type="button"
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '0 12px',
              height: 32,
              fontSize: 12,
              fontFamily: 'var(--font-sans)',
              background: t.path === activePath ? 'var(--color-paper)' : 'transparent',
              color: t.path === activePath ? 'var(--color-ink)' : 'var(--color-ink-3)',
              cursor: 'default',
              border: 'none',
              borderRight: '1px solid var(--color-border)',
              borderBottom: t.path === activePath ? '2px solid var(--color-ink)' : '2px solid transparent',
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
            onClick={() => setActivePath(t.path)}
          >
            <span>{t.path.split(/[/\\]/).pop()}</span>
            {t.dirty && <span style={{ color: 'var(--color-ink-3)', fontSize: 11 }}>●</span>}
            <span
              style={{ color: 'var(--color-ink-4)', fontSize: 12, cursor: 'default', marginLeft: 2 }}
              onClick={(e) => { e.stopPropagation(); closeTab(t.path) }}
            >
              ×
            </span>
          </button>
        ))}
      </div>
      <div className="editor-host min-h-0 flex-1">
        {active ? (
          <Editor
            height="100%"
            theme="po-paper"
            beforeMount={handleBeforeMount}
            language={active.language}
            value={active.content}
            path={active.path}
            options={{
              fontSize: 13,
              fontFamily: 'JetBrains Mono, Cascadia Code, Consolas, monospace',
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              automaticLayout: true,
              padding: { top: 12 },
              renderLineHighlight: 'gutter',
              folding: true,
              lineNumbersMinChars: 3,
              find: { addExtraSpaceOnTop: false },
            }}
            onChange={(v) => updateTab(active.path, { content: v ?? '', dirty: (v ?? '') !== active.original })}
          />
        ) : null}
      </div>
    </div>
  )
}
