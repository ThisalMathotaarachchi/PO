import { api } from '../api/client'
import type { FileEntry } from '../api/client'
import { languageForPath, usePoStore } from '../store'
import { useCallback, useEffect, useRef, useState } from 'react'

// ─── Inline create row ────────────────────────────────────────────────────────

function InlineCreate({ kind, onConfirm, onCancel }: {
  kind: 'file' | 'folder'
  onConfirm: (name: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => { inputRef.current?.focus() }, [])

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 8px' }}>
      <span style={{ width: 12, fontSize: 10, color: 'var(--color-ink-4)', flexShrink: 0 }}>
        {kind === 'folder' ? '▸' : '·'}
      </span>
      <input
        ref={inputRef}
        className="input-paper"
        style={{ flex: 1, padding: '2px 6px', fontSize: 12, borderRadius: 4 }}
        placeholder={kind === 'file' ? 'filename.txt' : 'folder-name'}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && value.trim()) onConfirm(value.trim())
          if (e.key === 'Escape') onCancel()
        }}
        onBlur={() => { if (value.trim()) onConfirm(value.trim()); else onCancel() }}
      />
    </div>
  )
}

// ─── Recursive file collect (for filter search) ───────────────────────────────

async function collectAllFiles(path: string, results: FileEntry[] = []): Promise<FileEntry[]> {
  try {
    const res = await api.listFiles(path)
    for (const e of res.entries) {
      if (e.is_dir) await collectAllFiles(e.path, results)
      else results.push(e)
    }
  } catch { /* ignore */ }
  return results
}

// ─── Tree node ────────────────────────────────────────────────────────────────

type NodeProps = {
  entry: FileEntry
  depth: number
  onOpen: (path: string) => void
  onContext: (e: React.MouseEvent, path: string, isDir: boolean) => void
}

function TreeNode({ entry, depth, onOpen, onContext }: NodeProps) {
  const [open, setOpen] = useState(depth < 1)
  const [children, setChildren] = useState<FileEntry[] | null>(null)
  const activePath      = usePoStore((s) => s.activePath)
  const explorerRefresh = usePoStore((s) => s.explorerRefresh)

  const load = useCallback(async () => {
    if (!entry.is_dir) return
    const res = await api.listFiles(entry.path)
    setChildren(res.entries)
  }, [entry.is_dir, entry.path])

  useEffect(() => {
    if (open && entry.is_dir) void load()
  }, [open, entry.is_dir, load, explorerRefresh])

  const isActive = activePath === entry.path

  return (
    <div>
      <button
        type="button"
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          width: '100%', textAlign: 'left',
          paddingLeft: 8 + depth * 14,
          paddingRight: 8, paddingTop: 3, paddingBottom: 3,
          fontSize: 12,
          background: isActive ? 'var(--color-paper-2)' : 'none',
          color: isActive ? 'var(--color-ink)' : 'var(--color-ink-2)',
          border: 'none', cursor: 'default',
          borderRadius: 4,
          fontFamily: 'var(--font-sans)',
        }}
        onClick={() => { if (entry.is_dir) setOpen((v) => !v); else onOpen(entry.path) }}
        onContextMenu={(e) => onContext(e, entry.path, entry.is_dir)}
      >
        <span style={{ width: 12, flexShrink: 0, fontSize: 10, color: 'var(--color-ink-4)' }}>
          {entry.is_dir ? (open ? '▾' : '▸') : '·'}
        </span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {entry.name}
        </span>
      </button>
      {open && children
        ? children.map((c) => (
            <TreeNode key={c.path} entry={c} depth={depth + 1} onOpen={onOpen} onContext={onContext} />
          ))
        : null}
    </div>
  )
}

// ─── Root Explorer ────────────────────────────────────────────────────────────

export function Explorer({ onAsk }: { onAsk: (prompt: string) => void }) {
  const [roots, setRoots]               = useState<FileEntry[]>([])
  const [filter, setFilter]             = useState('')
  const [searching, setSearching]       = useState(false)
  const [searchResults, setSearchResults] = useState<FileEntry[]>([])
  const [menu, setMenu]                 = useState<{ x: number; y: number; path: string; isDir: boolean } | null>(null)
  const [creating, setCreating]         = useState<'file' | 'folder' | null>(null)
  const explorerRefresh = usePoStore((s) => s.explorerRefresh)
  const openTab         = usePoStore((s) => s.openTab)
  const bumpExplorer    = usePoStore((s) => s.bumpExplorer)
  const workspace       = usePoStore((s) => s.workspace)
  const searchTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null)

  const reload = useCallback(async () => {
    if (!workspace) return
    const res = await api.listFiles('.')
    setRoots(res.entries)
  }, [workspace])

  useEffect(() => { void reload() }, [reload, explorerRefresh])

  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (!filter.trim()) { setSearchResults([]); setSearching(false); return }
    setSearching(true)
    searchTimerRef.current = setTimeout(async () => {
      try {
        const all = await collectAllFiles('.')
        const q = filter.toLowerCase()
        setSearchResults(all.filter((e) => e.name.toLowerCase().includes(q)))
      } catch { setSearchResults([]) }
      finally { setSearching(false) }
    }, 250)
    return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current) }
  }, [filter])

  async function openFile(path: string) {
    const file = await api.readFile(path)
    openTab({ path, content: file.content, original: file.content, dirty: false, language: languageForPath(path) })
  }

  async function handleCreate(kind: 'file' | 'folder', name: string) {
    setCreating(null)
    if (!name) return
    try {
      if (kind === 'file') await api.createFile(name, '')
      else await api.mkdir(name)
      bumpExplorer()
    } catch { /* ignore */ }
  }

  async function rename(path: string) {
    const next = window.prompt('Rename to', path)
    if (!next || next === path) return
    try { await api.renameFile(path, next); bumpExplorer() } catch { /* ignore */ }
  }

  async function remove(path: string, isDir: boolean) {
    const label = path.split(/[/\\]/).pop() ?? path
    const confirmMsg = isDir
      ? `Delete folder "${label}" and all its contents?`
      : `Delete "${label}"?`
    if (!window.confirm(confirmMsg)) return
    try {
      if (isDir) {
        await api.deleteDirectory(path)
      } else {
        await api.deleteFile(path)
      }
      bumpExplorer()
    } catch (err) {
      window.alert(`Delete failed: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  if (!workspace) {
    return (
      <div className="ruled-paper" style={{ height: '100%', padding: 16, fontSize: 12, color: 'var(--color-ink-4)', fontStyle: 'italic', background: 'var(--color-paper)' }}>
        Open a project to get started.
      </div>
    )
  }

  const showSearch = filter.trim().length > 0

  return (
    <div
      className="ruled-paper"
      style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--color-paper)' }}
      onClick={() => setMenu(null)}
    >
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '6px 10px',
        borderBottom: '1px solid var(--color-border)',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 10, letterSpacing: '0.12em', color: 'var(--color-ink-4)', fontWeight: 500 }}>
          EXPLORER
        </span>
        <div style={{ display: 'flex', gap: 2 }}>
          <button
            type="button"
            style={{ padding: '0 4px', fontSize: 14, color: 'var(--color-ink-4)', background: 'none', border: 'none', cursor: 'default' }}
            title="New file"
            onClick={() => setCreating('file')}
          >
            +
          </button>
          <button
            type="button"
            style={{ padding: '0 4px', fontSize: 12, color: 'var(--color-ink-4)', background: 'none', border: 'none', cursor: 'default' }}
            title="New folder"
            onClick={() => setCreating('folder')}
          >
            ▢
          </button>
        </div>
      </div>

      {/* Filter input — ruled-paper feel, no visible box */}
      <div style={{ padding: '6px 8px', flexShrink: 0 }}>
        <input
          className="input-paper"
          style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4 }}
          placeholder="Filter files…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      {/* Inline create */}
      {creating && (
        <div style={{ flexShrink: 0 }}>
          <InlineCreate
            kind={creating}
            onConfirm={(name) => void handleCreate(creating, name)}
            onCancel={() => setCreating(null)}
          />
        </div>
      )}

      {/* Tree or search results */}
      <div className="scrollbar-thin ruled-paper" style={{ flex: 1, overflowY: 'auto', padding: '4px 4px 8px', background: 'var(--color-paper)' }}>
        {showSearch ? (
          searching ? (
            <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--color-ink-4)' }}>Searching…</div>
          ) : searchResults.length === 0 ? (
            <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--color-ink-4)' }}>No files match "{filter}"</div>
          ) : searchResults.map((e) => (
            <button
              key={e.path}
              type="button"
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                width: '100%', textAlign: 'left',
                padding: '3px 8px', fontSize: 12,
                background: 'none', border: 'none', cursor: 'default', borderRadius: 4,
                color: 'var(--color-ink-2)',
              }}
              onClick={() => void openFile(e.path)}
              onContextMenu={(ev) => { ev.preventDefault(); setMenu({ x: ev.clientX, y: ev.clientY, path: e.path, isDir: false }) }}
            >
              <span style={{ width: 12, fontSize: 10, color: 'var(--color-ink-4)', flexShrink: 0 }}>·</span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.name}</span>
              <span style={{ fontSize: 10, color: 'var(--color-ink-4)', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 80 }}>
                {e.path.split(/[/\\]/).slice(0, -1).join('/')}
              </span>
            </button>
          ))
        ) : (
          roots.map((e) => (
            <TreeNode
              key={e.path}
              entry={e}
              depth={0}
              onOpen={(p) => void openFile(p)}
              onContext={(ev, path, isDir) => { ev.preventDefault(); setMenu({ x: ev.clientX, y: ev.clientY, path, isDir }) }}
            />
          ))
        )}
      </div>

      {/* Context menu — position:fixed so it escapes any clipping parent */}
      {menu && (
        <div
          style={{
            position: 'fixed',
            left: menu.x, top: menu.y,
            zIndex: 9999,
            minWidth: 180,
            background: '#FEFCF7',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
            padding: 4,
            boxShadow: '0 4px 16px rgba(28,25,23,0.14)',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {([
            ['Ask Po',        () => onAsk(`Help with ${menu.path}`)],
            ['Explain',       () => onAsk(`Explain ${menu.path}`)],
            ['Find problems', () => onAsk(`Find problems in ${menu.path}`)],
            ['Generate tests',() => onAsk(`Generate tests for ${menu.path}`)],
            ['Refactor',      () => onAsk(`Refactor ${menu.path}`)],
            null,
            ['Rename',        () => void rename(menu.path)],
            ['Delete',        () => void remove(menu.path, menu.isDir)],
          ] as Array<[string, () => void] | null>).map((item, i) =>
            item === null ? (
              <div key={`sep-${i}`} style={{ height: 1, background: 'var(--color-border-2)', margin: '3px 6px' }} />
            ) : (
              <button
                key={item[0]}
                type="button"
                className="menu-item w-full text-left"
                style={{ borderRadius: 5, padding: '5px 10px', fontSize: 12 }}
                onClick={() => { setMenu(null); item[1]() }}
              >
                {item[0]}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  )
}
