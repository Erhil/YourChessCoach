import { Chess } from 'chess.js'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { openingCard, type OpeningCardData } from '../api/openings'
import { toFigurine } from '../chess/notation'
import { Board } from './Board'
import { MoveList } from './MoveList'
import css from './OpeningCard.module.css'

const noMove = () => false

/** Bottom sheet with the opening the game is in: main line by steps, next moves, lesson and puzzles. */
export function OpeningCard({ moves, onClose }: { moves: string[]; onClose: () => void }) {
  const [card, setCard] = useState<OpeningCardData | null>(null)
  const [failed, setFailed] = useState(false)
  const [ply, setPly] = useState(0)
  useEffect(() => {
    openingCard(moves).then(
      (c) => {
        setCard(c)
        setPly(c.line_san.length)
      },
      () => setFailed(true),
    )
  }, [moves])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const chess = new Chess()
  const shown = card ? card.line_san.slice(0, ply).map((san) => chess.move(san)) : []
  const last = shown.at(-1)
  const n = card?.line_san.length ?? 0
  const number = Math.floor(n / 2) + 1
  const dots = n % 2 === 0 ? '.' : '…'
  return (
    <section className={css.sheet} role="dialog" aria-label="Карточка дебюта" data-testid="opening-card">
      <div className={css.head}>
        <h2>{card ? `${card.name} (${card.eco})` : 'Дебют'}</h2>
        <button type="button" aria-label="Закрыть карточку" onClick={onClose}>
          ✕
        </button>
      </div>
      {failed && <p>Не удалось загрузить карточку дебюта.</p>}
      {card && (
        <>
          <div className={css.board}>
            <Board
              position={chess.fen()}
              canMove={false}
              onMove={noMove}
              lastMove={last ? { from: last.from, to: last.to } : null}
            />
          </div>
          <div className={css.buttons}>
            <button type="button" aria-label="В начало" disabled={ply === 0} onClick={() => setPly(0)}>
              ⏮
            </button>
            <button type="button" aria-label="Назад" disabled={ply === 0} onClick={() => setPly(ply - 1)}>
              ◀
            </button>
            <button type="button" aria-label="Вперёд" disabled={ply === n} onClick={() => setPly(ply + 1)}>
              ▶
            </button>
          </div>
          <MoveList moves={card.line_san} current={ply - 1} onSelect={(p) => setPly(p + 1)} />
          {card.continuations.length > 0 && (
            <>
              <h3>Известные продолжения</h3>
              <ul className={css.next} data-testid="opening-next">
                {card.continuations.map((c) => (
                  <li key={c.san}>
                    <strong>
                      {number}
                      {dots} {toFigurine(c.san)}
                    </strong>{' '}
                    {c.name}
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className={css.links}>
            {card.lesson && <Link to={`/lessons/${card.lesson.slug}`}>Урок: {card.lesson.title}</Link>}
            {card.puzzles && (
              <Link to={`/puzzles?opening=${encodeURIComponent(card.puzzles)}`}>Задачи по этому дебюту</Link>
            )}
          </div>
        </>
      )}
    </section>
  )
}
