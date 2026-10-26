import type { Achievements } from '../../api/activity'
import type { NextMistake } from '../../api/mistakes'
import type { Progress } from '../../api/progress'
import { plural } from '../../plural'
import { deckLeft, lastEarned, topThemes } from '../../profile/summary'
import ActivityCalendar from '../ActivityCalendar'
import { Track } from './Charts'
import css from './Profile.module.css'
import { NoData, Tile } from './Tile'

/** Up to 4 themes, the highest rating first. */
export function ThemesTile({ themes }: { themes: Progress['themes'] }) {
  if (!themes.length) return <Tile label="Темы"><p className="muted">Решите задачи, чтобы увидеть темы</p></Tile>
  const { items, early } = topThemes(themes)
  return (
    <Tile label="Темы">
      <ul className={css.lines}>
        {items.map((t) => (
          <li key={t.key}>
            {t.name} <strong>{Math.round(t.rating)}</strong>
          </li>
        ))}
      </ul>
      {early && <p className="muted">По первым попыткам</p>}
    </Tile>
  )
}

/** Cards for today and the learned cards of the deck. `next`: `undefined` while loading, `null` after a failure. */
export function DeckTile({ m, next }: { m: Progress['mistakes']; next: NextMistake | null | undefined }) {
  return (
    <Tile label="Колода" value={next ? `${deckLeft(next)} на сегодня` : <NoData loading={next === undefined} />}>
      <p className="muted">
        усвоено {m.learned} из {m.total}
      </p>
      <Track done={m.learned} total={m.total} label="Усвоено карточек" />
    </Tile>
  )
}

export function LessonsTile({ l }: { l: Progress['lessons'] }) {
  return (
    <Tile label="Уроки" value={`${l.completed} из ${l.total}`}>
      <Track done={l.completed} total={l.total} label="Пройдено уроков" />
    </Tile>
  )
}

/** The number of earned achievements, the last one and the nearest goal. */
export function AchievementsTile({ ach }: { ach: Achievements | null | undefined }) {
  if (!ach) return <Tile label="Достижения" value={<NoData loading={ach === undefined} />} wide />
  const n = ach.earned.length
  const last = lastEarned(ach.earned)
  const goal = ach.next[0]
  return (
    <Tile label="Достижения" value={`${n} из ${ach.total}`} wide>
      {last && <p>Последнее: {last.title}</p>}
      {goal && (
        <p className="muted">
          Ближайшее: {goal.title}
          {goal.target > 1 && ` — ${Math.min(goal.progress, goal.target)} из ${goal.target}`}
        </p>
      )}
    </Tile>
  )
}

/** The active days of the last 12 weeks; the count and the caption beside the grid. */
export function CalendarTile({ dates, now }: { dates: string[]; now: Date }) {
  const n = dates.length
  return (
    <Tile label="Календарь" wide>
      <ActivityCalendar dates={dates} now={now}>
        <p className={css.value}>
          {n} {plural(n, 'активный день', 'активных дня', 'активных дней')} за 12 недель
        </p>
        <p className="muted">Закрашены дни с занятиями, сегодня — в рамке</p>
      </ActivityCalendar>
    </Tile>
  )
}
