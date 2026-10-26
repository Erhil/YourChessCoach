import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { popClass } from '../motion'
import { canSwap, isDone, loadShown, storeShown, type Task } from '../today/dailyTasks'
import css from './Today.module.css'

/**
 * The three tasks of the day with progress and a check mark; one not-done task can be swapped for the spare.
 * A check mark animates once: the first time the page shows the task done on this local day.
 */
export default function DailyTasks({ tasks, spare, swapped, onSwap, date }: {
  tasks: Task[]
  spare: Task | null
  swapped: boolean
  onSwap: (t: Task) => void
  /** The local date; empty when unknown, then nothing animates. */
  date: string
}) {
  const [shown] = useState(() => (date ? loadShown(date) : null))
  const doneKey = tasks.filter(isDone).map((t) => t.kind).join(',')
  useEffect(() => {
    if (!date || !doneKey) return
    const kinds = loadShown(date)
    const add = doneKey.split(',').filter((k) => !kinds.includes(k as Task['kind'])) as Task['kind'][]
    if (add.length) storeShown(date, [...kinds, ...add])
  }, [date, doneKey])
  return (
    <section aria-label="Задания дня">
      <h2>Задания дня</h2>
      <ol className={css.tasks}>
        {tasks.map((t) => (
          <li key={t.kind} className={css.task} data-testid={`task-${t.kind}`}>
            <Link to={t.to} className={css.link}>
              <span className={css.text}>{t.text}</span>
              <span className={css.meta}>{t.time}</span>
              <span className={css.meta} data-testid="task-progress">
                {t.done}/{t.target}
              </span>
              {isDone(t) && (
                <span className={`${css.done} ${shown && !shown.includes(t.kind) ? popClass() : ''}`} aria-label="выполнено">
                  ✓
                </span>
              )}
            </Link>
            {canSwap(t, spare, swapped) && (
              <button type="button" className={css.swap} onClick={() => onSwap(t)}>
                Заменить
              </button>
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}
