import type { ReactNode } from 'react'
import css from './Profile.module.css'

export interface Change {
  text: string
  /** A good change is in the accent colour; a bad or no change is muted. The text says the direction too. */
  good: boolean
}

/** A summary tile: a short label, a value, an optional change and an optional mini chart. */
export function Tile({ label, value, change, main, wide, children }: {
  label: string
  value?: ReactNode
  change?: Change | null
  main?: boolean
  wide?: boolean
  children?: ReactNode
}) {
  return (
    <div role="group" aria-label={label} data-testid="tile" className={[css.tile, wide ? css.wide : ''].join(' ')}>
      <p className={css.label}>{label}</p>
      {value !== undefined && <p className={main ? css.big : css.value}>{value}</p>}
      {change && (
        <p className={change.good ? css.good : 'muted'} data-testid="change">
          {change.text}
        </p>
      )}
      {children}
    </div>
  )
}

/** The value of a tile without its data: «…» while the request runs, «нет данных» after it failed. */
export function NoData({ loading }: { loading: boolean }) {
  return loading ? '…' : <span className="muted">нет данных</span>
}
