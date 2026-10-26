import type { Progress } from '../api/progress'
import { plural } from '../plural'
import { RatingChart } from './RatingChart'
import css from './ProgressDetails.module.css'

/** The detail blocks of the progress; `chartTitle` replaces the heading with the rating (the profile shows the rating in its summary). */
export function ProgressView({ d, chartTitle }: { d: Progress; chartTitle?: string }) {
  const g = d.games
  return (
    <>
      <h2>{chartTitle ?? `Рейтинг в задачах: ${Math.round(d.puzzles.rating)}`}</h2>
      <RatingChart points={d.puzzles.history.map((h) => Math.round(h.rating))} />
      <p className="muted">
        Попыток: {d.puzzles.attempts}, решено: {d.puzzles.solved}
      </p>
      <h2>Темы</h2>
      {d.themes.length === 0 ? (
        <p className="muted">Пока нет данных по темам.</p>
      ) : (
        <table className={css.table}>
          <thead>
            <tr>
              <th>Тема</th>
              <th>Рейтинг</th>
              <th>Попыток</th>
            </tr>
          </thead>
          <tbody>
            {d.themes.map((t) => (
              <tr key={t.key} className={t.key === d.weak_theme?.key ? css.weak : undefined}>
                <td>
                  {t.name}
                  {t.key === d.weak_theme?.key && ' (слабая)'}
                </td>
                <td>{Math.round(t.rating)}</td>
                <td>{t.attempts}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h2>Партии</h2>
      <p>
        Сыграно: {g.count}. Побед: {g.wins}, ничьих: {g.draws}, поражений: {g.losses}.
        {(g.training ?? 0) > 0 && ` Тренировочных: ${g.training}, их результат не считается.`}
      </p>
      {g.player_moves > 0 && <p>Зевков на 10 ходов: {g.blunders_per_10_moves.toFixed(1)}</p>}
      <h2>Уроки</h2>
      <p>
        Уроки: {d.lessons.completed} из {d.lessons.total} пройдено
      </p>
      <h2>Колода ошибок</h2>
      <p>
        В колоде: {d.mistakes.total} {plural(d.mistakes.total, 'карточка', 'карточки', 'карточек')}, усвоено: {d.mistakes.learned}
      </p>
    </>
  )
}
