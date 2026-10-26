export function RatingChart({ points }: { points: number[] }) {
  if (points.length < 2) return <p className="muted">Решите несколько задач, чтобы увидеть график</p>
  const W = 320
  const H = 140
  const pad = 12
  const lo = Math.min(...points)
  const hi = Math.max(...points)
  const span = hi - lo || 1
  const xy = points.map((v, i) => [
    pad + (i * (W - 2 * pad)) / (points.length - 1),
    H - pad - ((v - lo) * (H - 2 * pad)) / span,
  ])
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`График рейтинга: от ${lo} до ${hi}`}
      style={{ width: '100%', height: 'auto', display: 'block' }}
    >
      <polyline
        points={xy.map((p) => p.join(',')).join(' ')}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <circle cx={xy.at(-1)![0]} cy={xy.at(-1)![1]} r="4" fill="var(--accent)" />
      <text x={pad} y={10} fontSize="11" fill="var(--muted)">{hi}</text>
      <text x={pad} y={H - 2} fontSize="11" fill="var(--muted)">{lo}</text>
    </svg>
  )
}
