/**
 * PoMark — the canonical Po panda/orb identity mark.
 *
 * A minimalist geometric panda constructed from clean ink shapes.
 * Works at any size, in any context: navbar, empty state, splash, favicon.
 *
 * Design language:
 *   - Round face / orb form
 *   - Two semi-circular ears at top
 *   - Large ink eye patches (the characteristic panda feature)
 *   - Simple dot eyes
 *   - Small mouth
 *   - Thin circular orbit ring (the "orb" element)
 *   - All ink-on-paper — no gradients, no glow
 */

export function PoMark({
  size = 32,
  color = 'currentColor',
  className = '',
}: {
  size?: number
  color?: string
  className?: string
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Po"
      role="img"
    >
      {/* Outer orbit ring */}
      <circle
        cx="24"
        cy="26"
        r="21"
        stroke={color}
        strokeWidth="1.2"
        strokeOpacity="0.18"
        fill="none"
      />

      {/* Left ear */}
      <ellipse cx="11" cy="9" rx="5.5" ry="6.5" fill={color} />
      {/* Right ear */}
      <ellipse cx="37" cy="9" rx="5.5" ry="6.5" fill={color} />

      {/* Face circle */}
      <circle cx="24" cy="26" r="18" fill={color} fillOpacity="0.06" stroke={color} strokeWidth="1.4" />

      {/* Left eye patch */}
      <ellipse
        cx="17"
        cy="23"
        rx="6"
        ry="7.5"
        fill={color}
        transform="rotate(-10 17 23)"
      />
      {/* Right eye patch */}
      <ellipse
        cx="31"
        cy="23"
        rx="6"
        ry="7.5"
        fill={color}
        transform="rotate(10 31 23)"
      />

      {/* Left eye */}
      <circle cx="17" cy="22" r="2.5" fill={color} fillOpacity="0.05" />
      <circle cx="17" cy="22" r="1.4" fill="white" />
      {/* Right eye */}
      <circle cx="31" cy="22" r="2.5" fill={color} fillOpacity="0.05" />
      <circle cx="31" cy="22" r="1.4" fill="white" />

      {/* Nose */}
      <ellipse cx="24" cy="30" rx="1.8" ry="1.2" fill={color} fillOpacity="0.4" />

      {/* Mouth — calm */}
      <path
        d="M 20 33 Q 24 36 28 33"
        stroke={color}
        strokeWidth="1.3"
        strokeLinecap="round"
        fill="none"
        strokeOpacity="0.5"
      />
    </svg>
  )
}

/**
 * PoMarkAnimated — the PoMark with breathing animation for active states.
 * Used in AgentPanel header and empty states.
 */
export function PoMarkAnimated({
  size = 48,
  state = 'idle',
}: {
  size?: number
  state?: 'idle' | 'working' | 'error'
}) {
  const animClass =
    state === 'working' ? 'orb-active' :
    state === 'error'   ? 'orb-error'  :
    'orb-idle'

  return (
    <div className={animClass} style={{ display: 'inline-flex' }}>
      <PoMark size={size} color="#1C1917" />
    </div>
  )
}
