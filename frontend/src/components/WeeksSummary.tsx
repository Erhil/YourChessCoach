import type { WeekSummary } from '../api/progress'
import css from './ProgressDetails.module.css'
import tcss from './Today.module.css'

/** «с 13.10» from YYYY-MM-DD. */
const since = (iso: string) => `с ${iso.slice(8, 10)}.${iso.slice(5, 7)}`
/** «+35», «−10», «0». */
const signed = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : '0')
/** «1,2» or «—» when there were no own moves. */
const per10 = (x: number | null) => (x === null ? '—' : x.toFixed(1).replace('.', ','))

/** The last weeks with activity, newest first, and the blunders trend as bars (oldest on the left); hidden without activity. */
export default function WeeksSummary({ weeks: all }: { weeks: WeekSummary[] }) {
  const weeks = all.filter((w) => w.active_days > 0)
  const bars = weeks.filter((w) => w.blunders_per_10_moves !== null)
  if (!weeks.length) return null
  const max = Math.max(0, ...bars.map((w) => w.blunders_per_10_moves ?? 0))
  return (
    <section aria-label="Последние недели" className={tcss.card}>
      <h2>Последние недели</h2>
      <ul className={css.weeks}>
        {[...weeks].reverse().map((w) => (
          <li key={w.start} data-testid="week">
            <strong>{since(w.start)}</strong>
            <span>дней: {w.active_days}</span>
            <span>задач решено: {w.puzzles_solved}</span>
            <span>рейтинг: {signed(w.rating_change)}</span>
            <span>зевки на 10 ходов: {per10(w.blunders_per_10_moves)}</span>
            {w.games > 0 && <span>учтено партий: {w.analyzed_games} из {w.games}</span>}
          </li>
        ))}
      </ul>
      {bars.length > 0 && (
        <>
          <h3 className={css.sub}>Зевки на 10 ходов по неделям</h3>
          <div className={css.bars} aria-hidden="true">
            {bars.map((w) => (
              <div key={w.start} className={css.barCol}>
                {/* 80% at most: the rest is room for the label. */}
                <span className={css.barFill} style={{ height: `${max ? (80 * (w.blunders_per_10_moves ?? 0)) / max : 0}%` }} />
                <span className={css.barLabel}>{w.start.slice(8, 10)}.{w.start.slice(5, 7)}</span>
              </div>
            ))}
          </div>
          <p className="muted">Чем ниже, тем лучше.</p>
        </>
      )}
    </section>
  )
}
