import type { Activity } from '../api/activity'
import { plural } from '../plural'
import css from './Today.module.css'

const NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const GOALS = [3, 4, 5]
const dayIndex = (start: string, date: string) => Math.round((Date.parse(date) - Date.parse(start)) / 86_400_000)

/** «На этой неделе: N из M дней» (no zero: «Цель недели — M дня» before the first active day), the 7 days and the goal choice. Missed days have no mark of their own. */
export default function WeekBlock({ week, date, onGoal }: { week: Activity['week']; date: string; onGoal: (goal: number) => void }) {
  const today = dayIndex(week.start, date)
  return (
    <section aria-label="Неделя" className={css.card}>
      <h2>
        {week.active_days > 0
          ? `На этой неделе: ${week.active_days} из ${week.goal} дней`
          : `Цель недели — ${week.goal} ${plural(week.goal, 'день', 'дня', 'дней')}`}
      </h2>
      <ol className={css.days}>
        {week.days.map((active, i) => (
          <li
            key={NAMES[i]}
            className={[css.day, active ? css.active : '', i === today ? css.today : ''].join(' ')}
            aria-label={`${NAMES[i]}${i === today ? ', сегодня' : ''}${active ? ': занимались' : ''}`}
          >
            <span className={css.mark} />
            {NAMES[i]}
          </li>
        ))}
      </ol>
      {week.met && <p>Цель недели выполнена</p>}
      {week.streak_weeks >= 1 && (
        <p>Цель выполнена {week.streak_weeks} {plural(week.streak_weeks, 'неделю', 'недели', 'недель')} подряд</p>
      )}
      <div role="group" aria-label="Цель недели" className={css.goal}>
        <span className="muted">Цель недели, дней:</span>
        {GOALS.map((g) => (
          <button key={g} type="button" aria-pressed={week.goal === g} onClick={() => week.goal !== g && onGoal(g)}>
            {g}
          </button>
        ))}
      </div>
    </section>
  )
}
