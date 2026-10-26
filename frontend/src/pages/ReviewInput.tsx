import { useEffect, useState } from 'react'
import { getGames, type GameRow } from '../api/review'
import css from './Review.module.css'

type Props = {
  busy: boolean
  onGame: (id: number) => void
  onPgn: (pgn: string, side: 'white' | 'black') => void
}

export function ReviewInput({ busy, onGame, onPgn }: Props) {
  const [games, setGames] = useState<GameRow[]>([])
  const [pgn, setPgn] = useState('')
  const [side, setSide] = useState<'white' | 'black'>('white')
  useEffect(() => {
    getGames().then(setGames, () => setGames([]))
  }, [])

  return (
    <div className={css.input}>
      <section>
        <h2>Мои партии</h2>
        {games.length === 0 && <p className="muted">Сохранённых партий пока нет.</p>}
        <ul className={css.games}>
          {games.map((g) => (
            <li key={g.id}>
              <span>
                {g.created_at.slice(0, 10)}, {g.player_color === 'white' ? 'белыми' : 'чёрными'}
                {g.level ? `, уровень ${g.level}` : ''}, {g.result}
                {g.training && ', тренировочная'}
              </span>
              <button type="button" disabled={busy} onClick={() => onGame(g.id)}>
                Разобрать
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2>Вставьте PGN</h2>
        <textarea aria-label="Вставьте PGN" rows={5} value={pgn} onChange={(e) => setPgn(e.target.value)} />
        <div className={css.row}>
          <label className="choice">
            <input type="radio" name="side" checked={side === 'white'} onChange={() => setSide('white')} />
            Я играл белыми
          </label>
          <label className="choice">
            <input type="radio" name="side" checked={side === 'black'} onChange={() => setSide('black')} />
            Я играл чёрными
          </label>
        </div>
        <button type="button" disabled={busy || !pgn.trim()} onClick={() => onPgn(pgn, side)}>
          Разобрать
        </button>
      </section>
    </div>
  )
}
