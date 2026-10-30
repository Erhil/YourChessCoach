import type { Activity } from '../../api/activity'
import type { Progress } from '../../api/progress'
import { plural } from '../../plural'
import { blunderTrend, comma, dayMonth, ratingChange, signed } from '../../profile/summary'
import { Bars, Chart, Sparkline } from './Charts'
import css from './Profile.module.css'
import { NoData, Tile } from './Tile'

const NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const POINTS = 30

/** The main number of the page: the puzzle rating, its change (in 7 days or since the first puzzle) and the recent ratings. */
export function RatingTile({ p, now }: { p: Progress['puzzles']; now: Date }) {
  const { value: change, since } = ratingChange(p, now)
  const recent = p.history.slice(-POINTS)
  const last = recent.at(-1)
  return (
    <Tile
      label="Рейтинг в задачах"
      value={Math.round(p.rating)}
      main
      wide
      change={{ text: `${signed(change)} ${since}`, good: change > 0 }}
    >
      {last ? (
        <Chart
          label={`Рейтинг за последние ${recent.length} ${plural(recent.length, 'попытку', 'попытки', 'попыток')}: от ${Math.min(...recent.map((h) => h.rating))} до ${Math.max(...recent.map((h) => h.rating))}, сейчас ${last.rating}`}
          idle={`Последняя задача ${dayMonth(last.at)}: ${last.rating}`}
          texts={recent.map((h) => `${dayMonth(h.at)}: ${h.rating}`)}
        >
          <Sparkline values={recent.map((h) => h.rating)} />
        </Chart>
      ) : (
        <p className="muted">Решите задачу, чтобы увидеть график</p>
      )}
    </Tile>
  )
}

/** «N из M дней» of this week, the 7 days and the streak of weeks with the goal met. `undefined`: loading, `null`: failed. */
export function WeekTile({ a }: { a: Activity | null | undefined }) {
  if (!a) return <Tile label="Неделя" value={<NoData loading={a === undefined} />} />
  const w = a.week
  const today = Math.round((Date.parse(a.date) - Date.parse(w.start)) / 86_400_000)
  const texts = w.days.map((on, i) => `${NAMES[i]}${i === today ? ', сегодня' : ''}: ${on ? 'занимались' : 'занятий не было'}`)
  return (
    <Tile label="Неделя" value={`${w.active_days} из ${w.goal} дней`}>
      <Chart label={texts.join('; ')} idle={w.met ? 'Цель недели выполнена' : `Цель — ${w.goal} ${plural(w.goal, 'день', 'дня', 'дней')}`} texts={texts}>
        <div className={css.marks}>
          {w.days.map((on, i) => (
            <span key={NAMES[i]} data-i={i} className={[css.markCol, on ? css.on : '', i === today ? css.today : ''].join(' ')}>
              <span className={css.mark} />
              {NAMES[i][0]}
            </span>
          ))}
        </div>
      </Chart>
      {w.streak_weeks >= 1 && (
        <p className="muted">
          Цель выполнена {w.streak_weeks} {plural(w.streak_weeks, 'неделю', 'недели', 'недель')} подряд
        </p>
      )}
    </Tile>
  )
}

/** The blunder rate of the latest week with games and its change; down is good. */
export function BlundersTile({ weeks }: { weeks: Progress['weeks'] }) {
  const t = blunderTrend(weeks ?? [])
  if (!t) return <Tile label="Зевки на 10 ходов" value="—"><p className="muted">Сохраните и разберите партию, чтобы увидеть</p></Tile>
  const c = t.change
  const change =
    c === null ? null : c === 0 ? { text: 'без изменений', good: false } : { text: `${signed(c, 1)} · ${c < 0 ? 'лучше' : 'хуже'}, чем ${t.than}`, good: c < 0 }
  const shown = t.known.slice(-8)
  const texts = shown.map((w) => `с ${dayMonth(w.start)}: ${comma(w.blunders_per_10_moves!)}`)
  return (
    <Tile label="Зевки на 10 ходов" value={comma(t.value)} change={change}>
      <p className="muted">Учтено партий за неделю: {t.latest.analyzed_games} из {t.latest.games}</p>
      <Chart label={`Зевки на 10 ходов по неделям: ${texts.join('; ')}`} idle={`Неделя с ${dayMonth(t.latest.start)}`} texts={texts}>
        <Bars values={shown.map((w) => w.blunders_per_10_moves!)} />
      </Chart>
    </Tile>
  )
}

/** Wins, draws and losses without the training games; the training games apart. */
export function GamesTile({ g }: { g: Progress['games'] }) {
  return (
    <Tile label="Партии">
      <p>
        <strong>{g.wins}</strong> {plural(g.wins, 'победа', 'победы', 'побед')} · <strong>{g.draws}</strong>{' '}
        {plural(g.draws, 'ничья', 'ничьи', 'ничьих')} · <strong>{g.losses}</strong> {plural(g.losses, 'поражение', 'поражения', 'поражений')}
      </p>
      {(g.training ?? 0) > 0 && <p className="muted">тренировочных: {g.training}</p>}
    </Tile>
  )
}
