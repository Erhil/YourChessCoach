import { useNavigate, useSearchParams } from 'react-router-dom'
import { Board } from '../components/Board'
import { CoachPanel } from '../components/CoachPanel'
import { usePuzzle } from '../puzzles/usePuzzle'
import css from './Puzzles.module.css'

const sign = (n: number) => (n > 0 ? `+${n}` : String(n))

export default function Puzzles() {
  const z = usePuzzle()
  const navigate = useNavigate()
  // «Одна задача» from «Сегодня»: after the end the learner chooses one more or a stop.
  const one = useSearchParams()[0].get('one') === '1'
  const ended = z.phase === 'solved' || z.phase === 'failed' || z.phase === 'solution'
  const color = z.p?.player_color ?? 'white'
  const status = {
    loading: 'Загружаю задачу…',
    opp: 'Соперник ходит…',
    play: `Ваш ход: найдите лучший ход за ${color === 'white' ? 'белых' : 'чёрных'}`,
    solved: 'Решено!',
    failed: 'Неверно',
    solution: 'Решение:',
    error: 'Не удалось загрузить задачу.',
  }[z.phase]

  return (
    <>
      <h1>Задачи</h1>
      <div className={css.layout}>
        <Board
          position={z.fen}
          orientation={color}
          canMove={z.phase === 'play'}
          onMove={z.move}
          lastMove={z.lastMove}
          highlights={z.highlights}
          arrows={z.arrows}
        />
        <div className={css.side}>
          <div className={css.controls}>
            <label className="choice">
              Тема
              <select value={z.theme} onChange={(e) => z.setTheme(e.target.value)}>
                <option value="">Смешанные</option>
                {z.themes.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="choice">
              Дебют
              <select value={z.opening} onChange={(e) => z.setOpening(e.target.value)}>
                <option value="">Любой</option>
                {z.openings.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            {z.rating !== null && <span>Ваш рейтинг: {z.rating}</span>}
          </div>
          <p className={css.status} data-testid="status" role="status">{status}</p>
          {z.result && (
            <p data-testid="rating-change">
              Рейтинг: {sign(Math.round(z.result.delta))} (теперь {Math.round(z.result.rating_after)})
            </p>
          )}
          {z.hintText && <p>{z.hintText}</p>}
          {z.phase === 'failed' && z.coach !== undefined && <CoachPanel text={z.coach.text} source={z.coach.source} />}
          <div className={css.controls}>
            {z.phase === 'play' && (
              <button type="button" onClick={z.hint} disabled={z.hints >= 2}>
                Подсказка
              </button>
            )}
            {(z.phase === 'failed' || z.phase === 'play') && (
              <button type="button" onClick={z.showSolution}>
                Показать решение
              </button>
            )}
            {one && ended ? (
              <>
                <button type="button" onClick={z.next}>
                  Ещё одну?
                </button>
                <button type="button" onClick={() => navigate('/')}>
                  На сегодня хватит
                </button>
              </>
            ) : (
              <button type="button" onClick={z.next} disabled={z.phase === 'loading'}>
                Следующая задача
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
