import { Chess } from 'chess.js'
import { useEffect, useState } from 'react'
import { coachMove, type LessonSegment } from '../api/client'
import { openingName } from '../api/openings'
import { Board, type Move } from '../components/Board'
import { CoachPanel } from '../components/CoachPanel'
import { toFigurine, toUci } from '../chess/notation'
import css from './LineViewer.module.css'

type Block = Extract<LessonSegment, { type: 'line' }>

const NOT_IN_LINE = 'Этот ход не совпадает с линией урока. Попробуйте другой.'
const START_BOARD = new Chess().fen().split(' ')[0]

/** The student plays the moves of `side`; the app answers with the other side's moves of the line. */
export function LineTrainer({ block, onExit }: { block: Block; onExit: () => void }) {
  const { fen, moves, side } = block
  const [ply, setPly] = useState(0)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ ply: number; text: string; source?: string } | null>(null)
  const chess = new Chess(fen)
  const line = moves.slice(0, ply).map((m) => chess.move(m.san))
  const last = line.at(-1)
  const done = ply === moves.length
  const myTurn = !done && chess.turn() === side[0]

  useEffect(() => {
    if (done || myTurn) return
    const t = setTimeout(() => setPly(ply + 1), 400)
    return () => clearTimeout(t)
  }, [ply, done, myTurn])

  const onMove = (m: Move): boolean => {
    const expected = new Chess(chess.fen()).move(moves[ply].san)
    if (toUci(m) === toUci(expected)) {
      setNote(null)
      setPly(ply + 1)
      return true
    }
    const before = chess.fen()
    const uci = toUci(m)
    const show = (text: string, source?: string) => setNote({ ply, text, source })
    const tried = line.map(toUci).concat(uci)
    const book = fen.split(' ')[0] === START_BOARD ? openingName(tried).catch(() => null) : Promise.resolve(null)
    setBusy(true)
    void book
      .then(async (r) => {
        if (r?.exact) return show(`Это тоже известный ход: ${r.name}. В уроке разбираем ход ${toFigurine(moves[ply].san)}.`)
        const c = await coachMove(before, uci).catch(() => null)
        const why = c?.explanation?.text
        show(why ? `${NOT_IN_LINE} ${why}` : NOT_IN_LINE, c?.explanation?.source)
      })
      .finally(() => setBusy(false))
    return false
  }

  const current = ply > 0 ? moves[ply - 1] : null
  return (
    <section className={css.box} data-testid="line-trainer">
      <h3 className={css.title}>{block.title}</h3>
      <Board
        position={chess.fen()}
        orientation={side}
        canMove={myTurn && !busy}
        onMove={onMove}
        lastMove={last ? { from: last.from, to: last.to } : null}
      />
      <div className={css.buttons}>
        <button type="button" onClick={onExit}>
          Выйти из тренировки
        </button>
      </div>
      <div className={css.explain} role="status" data-testid="trainer-status">
        {done ? (
          <p className={css.done}>Линия пройдена!</p>
        ) : (
          <p className="muted">{myTurn ? 'Ваш ход: сыграйте ход из линии.' : 'Соперник отвечает…'}</p>
        )}
        {current && <p>{current.text}</p>}
      </div>
      {note && note.ply === ply && <CoachPanel text={note.text} source={note.source} />}
    </section>
  )
}
