type OrbMood =
  | 'idle'
  | 'understanding'
  | 'exploring'
  | 'executing'
  | 'testing'
  | 'waiting'
  | 'error'
  | 'success'

const STATE_MAP: Record<string, OrbMood> = {
  IDLE:                 'idle',
  UNDERSTANDING:        'understanding',
  EXPLORING:            'exploring',
  PLANNING:             'understanding',
  EXECUTING:            'executing',
  TESTING:              'testing',
  DEBUGGING:            'executing',
  VERIFYING:            'testing',
  COMPLETED:            'success',
  WAITING_FOR_APPROVAL: 'waiting',
  ERROR:                'error',
  CANCELLED:            'idle',
}

export function moodFromState(state: string): OrbMood {
  return STATE_MAP[state] ?? 'idle'
}

/**
 * Po's panda/orb identity.
 *
 * The SVG is drawn at viewBox 0 0 128 128. Key anatomy:
 *  - Two dark rounded ears above the sphere (panda ears)
 *  - A white-gradient sphere body
 *  - Two dark eye patches (oval, angled slightly)
 *  - Two white iris dots with a bright highlight each
 *  - A tiny neutral mouth
 *  - When active: a slow-rotating dashed ring around the orb
 */
export function PoOrb({
  state = 'IDLE',
  size = 88,
  label,
}: {
  state?: string
  size?: number
  label?: string
}) {
  const mood = moodFromState(state)
  const isActive  = mood === 'executing' || mood === 'testing'
  const isError   = mood === 'error'
  const isSuccess = mood === 'success'

  const animCls = isError
    ? 'orb-error'
    : isActive
    ? 'orb-active'
    : 'orb-idle'

  const glowColor = isError
    ? 'rgba(28,25,23,0.08)'
    : isSuccess
    ? 'rgba(28,25,23,0.12)'
    : mood === 'waiting'
    ? 'rgba(28,25,23,0.06)'
    : 'rgba(28,25,23,0.10)'

  const glowRadius = Math.round(size / 6)
  const gradId = `orb-grad-${size}`

  return (
    <div
      className={`inline-flex flex-col items-center ${animCls}`}
      style={{ width: size, height: size, filter: `drop-shadow(0 0 ${glowRadius}px ${glowColor})` }}
      aria-label={label || 'Po'}
      role="img"
    >
      <svg viewBox="0 0 128 128" width={size} height={size} aria-hidden>
        <defs>
          <radialGradient id={gradId} cx="38%" cy="32%" r="62%">
            <stop offset="0%"   stopColor="#ffffff" stopOpacity="0.98" />
            <stop offset="40%"  stopColor="#d8d8d8" stopOpacity="0.60" />
            <stop offset="100%" stopColor="#080808" stopOpacity="0.90" />
          </radialGradient>
        </defs>

        {/* ── Panda ears (above the sphere) ── */}
        <ellipse cx="30" cy="22" rx="14" ry="16" fill="#111" />
        <ellipse cx="98" cy="22" rx="14" ry="16" fill="#111" />
        {/* Slightly lighter inner ear */}
        <ellipse cx="30" cy="23" rx="7"  ry="8"  fill="#1e1e1e" />
        <ellipse cx="98" cy="23" rx="7"  ry="8"  fill="#1e1e1e" />

        {/* ── Sphere body ── */}
        <circle
          cx="64" cy="68" r="52"
          fill={`url(#${gradId})`}
          stroke="#fff"
          strokeOpacity="0.25"
          strokeWidth="1.2"
        />

        {/* ── Eye patches (dark ovals, tilted inward) ── */}
        <ellipse cx="45" cy="62" rx="14" ry="17" fill="#111" transform="rotate(-8 45 62)" />
        <ellipse cx="83" cy="62" rx="14" ry="17" fill="#111" transform="rotate(8 83 62)" />

        {/* ── Eyes (white irises + highlight) ── */}
        <circle cx="45" cy="63" r="6.5" fill="#f4f4f4" />
        <circle cx="83" cy="63" r="6.5" fill="#f4f4f4" />
        {/* Pupils */}
        <circle cx="46" cy="64" r="3.5" fill="#0a0a0a" />
        <circle cx="84" cy="64" r="3.5" fill="#0a0a0a" />
        {/* Catchlights */}
        <circle cx="48" cy="62" r="1.4" fill="#ffffff" opacity="0.9" />
        <circle cx="86" cy="62" r="1.4" fill="#ffffff" opacity="0.9" />

        {/* ── Mouth — calm neutral line ── */}
        <path
          d="M 57 80 Q 64 85 71 80"
          fill="none"
          stroke="#1a1a1a"
          strokeWidth="1.8"
          strokeLinecap="round"
        />

        {/* ── Activity ring (only when working/testing) ── */}
        {isActive && (
          <circle
            cx="64" cy="68" r="57"
            fill="none"
            stroke="#fff"
            strokeOpacity="0.10"
            strokeWidth="1.5"
            strokeDasharray="5 9"
          >
            <animateTransform
              attributeName="transform"
              type="rotate"
              from="0 64 68"
              to="360 64 68"
              dur="8s"
              repeatCount="indefinite"
            />
          </circle>
        )}

        {/* ── Success ring ── */}
        {isSuccess && (
          <circle
            cx="64" cy="68" r="57"
            fill="none"
            stroke="#fff"
            strokeOpacity="0.18"
            strokeWidth="1"
          />
        )}
      </svg>
    </div>
  )
}

export function statusLabel(kind: 'ready' | 'working' | 'waiting' | 'error'): string {
  switch (kind) {
    case 'working': return 'Working'
    case 'waiting': return 'Waiting'
    case 'error':   return 'Error'
    default:        return 'Ready'
  }
}
