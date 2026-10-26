import type { ReactNode } from 'react'
import { dayMonth } from '../profile/summary'
import css from './ActivityCalendar.module.css'

const NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const WEEKS = 12

/** The local date as YYYY-MM-DD. */
export const localIso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** The day cells of the grid: 12 full weeks from Monday, the week of `now` is the last one. */
export function gridDays(now: Date) {
  const today = localIso(now)
  const first = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7) - 7 * (WEEKS - 1))
  return Array.from({ length: WEEKS * 7 }, (_, i) => {
    const iso = localIso(new Date(first.getFullYear(), first.getMonth(), first.getDate() + i))
    return { iso, future: iso > today }
  })
}

/**
 * Active days of the last 12 weeks in a compact grid: a column for each week, a row for each weekday.
 * The cells are too small to tap, so they are not interactive: the label gives the count and the dates.
 * `children` (the text of the tile) goes beside the grid, or under it when the tile is narrow.
 */
export default function ActivityCalendar({ dates, now = new Date(), children }: { dates: string[]; now?: Date; children?: ReactNode }) {
  const active = new Set(dates)
  const today = localIso(now)
  const cells = gridDays(now)
  const days = cells.filter((c) => active.has(c.iso)).map((c) => dayMonth(c.iso) + (c.iso === today ? ' (сегодня)' : ''))
  const label = `Активных дней за 12 недель: ${days.length}${days.length ? `. Дни: ${days.join(', ')}` : ''}`
  return (
    <div className={css.row}>
      <div role="img" aria-label={label} className={css.calendar} data-testid="calendar">
        {NAMES.map((n) => (
          <span key={n} className={css.weekday}>
            {n}
          </span>
        ))}
        {cells.map((c) => (
          <span
            key={c.iso}
            data-date={c.iso}
            data-active={active.has(c.iso) || undefined}
            className={[css.cell, active.has(c.iso) ? css.on : '', c.iso === today ? css.now : '', c.future ? css.future : ''].join(' ')}
          />
        ))}
      </div>
      <div className={css.text}>{children}</div>
    </div>
  )
}
