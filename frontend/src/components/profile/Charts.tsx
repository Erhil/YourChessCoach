import { useState, type PointerEvent, type ReactNode } from 'react'
import css from './Profile.module.css'

/** The item under the pointer or the finger: a mouse shows it on hover, a tap shows it until the next tap. */
function usePick() {
  const [i, setI] = useState<number | null>(null)
  const at = (e: { target: EventTarget }) => {
    const el = (e.target as Element).closest('[data-i]')
    if (el) setI(Number(el.getAttribute('data-i')))
  }
  return {
    i,
    handlers: {
      onClick: at,
      onPointerMove: (e: PointerEvent) => e.pointerType === 'mouse' && at(e),
      onPointerLeave: (e: PointerEvent) => e.pointerType === 'mouse' && setI(null),
    },
  }
}

/** A mini chart: the picture for the eye, `label` for a screen reader, and a line with the picked value (else `idle`). */
export function Chart({ label, idle, texts, children, className }: {
  label: string
  idle: string
  texts: string[]
  children: ReactNode
  className?: string
}) {
  const { i, handlers } = usePick()
  return (
    <div className={css.chart}>
      <div role="img" aria-label={label} className={className} {...handlers}>
        {children}
      </div>
      <p className={css.caption} data-testid="chart-value" aria-hidden="true">
        {i === null ? idle : texts[i]}
      </p>
    </div>
  )
}

/** The rating line: the latest point in the accent colour, the rest muted. Each point has a full-height hit area. */
export function Sparkline({ values }: { values: number[] }) {
  const W = 200
  const H = 40
  const lo = Math.min(...values)
  const span = Math.max(...values) - lo || 1
  const step = values.length > 1 ? W / (values.length - 1) : 0
  const xy = values.map((v, k) => [values.length > 1 ? k * step : W / 2, H - 4 - ((v - lo) * (H - 8)) / span])
  const [lx, ly] = xy.at(-1)!
  return (
    <svg viewBox={`-4 0 ${W + 8} ${H}`} preserveAspectRatio="none" className={css.spark} aria-hidden="true">
      <polyline points={xy.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--muted)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      {/* A zero-length round-capped line stays a circle when the SVG stretches. */}
      <path d={`M${lx} ${ly}h0.01`} stroke="var(--accent)" strokeWidth="7" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {xy.map(([x], k) => (
        <rect key={k} data-i={k} x={x - (step || W) / 2} y={0} width={step || W} height={H} fill="transparent" />
      ))}
    </svg>
  )
}

/** Bars for the weeks, oldest on the left; the last bar in the accent colour. */
export function Bars({ values }: { values: number[] }) {
  const max = Math.max(0, ...values)
  return (
    <div className={css.bars}>
      {values.map((v, k) => (
        <span key={k} data-i={k} className={css.barCol}>
          <span className={k === values.length - 1 ? css.barLast : css.bar} style={{ height: `${max ? (100 * v) / max : 0}%` }} />
        </span>
      ))}
    </div>
  )
}

/** A progress track: «done» of «total». */
export function Track({ done, total, label }: { done: number; total: number; label: string }) {
  return (
    <div className={css.track} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
      <span style={{ width: `${total ? (100 * Math.min(done, total)) / total : 0}%` }} />
    </div>
  )
}
