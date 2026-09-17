import { useState } from 'react'

type Props = {
  open: boolean
  onClose: () => void
  actions: Array<{ id: string; label: string; run: () => void }>
}

export function CommandPalette({ open, onClose, actions }: Props) {
  const [q, setQ] = useState('')
  if (!open) return null
  const filtered = actions.filter((a) => a.label.toLowerCase().includes(q.toLowerCase()))

  return (
    <div
      className="modal-backdrop fixed inset-0 z-[5000] flex items-start justify-center pt-20"
      onClick={onClose}
    >
      <div
        className="modal-surface w-full max-w-lg overflow-hidden"
        style={{ zIndex: 5001 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ padding: '4px 4px 0' }}>
          <input
            autoFocus
            className="field"
            style={{ borderRadius: 8, fontSize: 14, padding: '10px 14px' }}
            placeholder="Type a command…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose()
              if (e.key === 'Enter' && filtered[0]) { filtered[0].run(); onClose() }
            }}
          />
        </div>
        <div className="scrollbar-thin" style={{ maxHeight: 320, overflow: 'auto', padding: '4px' }}>
          {filtered.map((a) => (
            <button
              key={a.id}
              type="button"
              className="menu-item w-full text-left"
              style={{ borderRadius: 6, padding: '8px 12px', fontSize: 13 }}
              onClick={() => { a.run(); onClose() }}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
