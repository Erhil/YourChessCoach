import { Chess } from 'chess.js'
import { useState } from 'react'
import type { LessonSegment } from '../api/client'
import { Board } from '../components/Board'
import { MoveList } from '../components/MoveList'
import { toFigurine } from '../chess/notation'
import { LineTrainer } from './LineTrainer'
import css from './LineViewer.module.css'

type Block = Extract<LessonSegment, { type: 'line' }>

const noMove = () => false

export function LineViewer({ block }: { block: Block }) {
  const { fen, moves, side } = block
  const [ply, setPly] = useState(0) // number of moves shown
  const [training, setTraining] = useState(false)
  const chess = new Chess(fen)
  const history = moves.slice(0, ply).map((m) => chess.move(m.san))
  const last = history.at(-1)
  const current = ply > 0 ? moves[ply - 1] : null
  const [startTurn, , , , , startNumber] = fen.split(' ')
  const offset = ply - 1 + (startTurn === 'b' ? 1 : 0)
  const number = (Number(startNumber) || 1) + Math.floor(offset / 2)
  const dots = offset % 2 === 0 ? '.' : '...'

  if (training) return <LineTrainer block={block} onExit={() => setTraining(false)} />

  return (
    <section className={css.box} data-testid="line">
      <h3 className={css.title}>{block.title}</h3>
      <Board
        position={chess.fen()}
        orientation={side}
        canMove={false}
        onMove={noMove}
        lastMove={last ? { from: last.from, to: last.to } : null}
      />
      <div className={css.buttons}>
        <button type="button" aria-label="В начало" disabled={ply === 0} onClick={() => setPly(0)}>
          ⏮
        </button>
        <button type="button" aria-label="Назад" disabled={ply === 0} onClick={() => setPly(ply - 1)}>
          ◀
        </button>
        <button type="button" aria-label="Вперёд" disabled={ply === moves.length} onClick={() => setPly(ply + 1)}>
          ▶
        </button>
        <button type="button" onClick={() => setTraining(true)}>
          Потренироваться
        </button>
      </div>
      <div className={css.explain} role="status" data-testid="line-explain">
        {current ? (
          <>
            <p className={css.move}>
              {number}
              {dots} {toFigurine(current.san)}
            </p>
            <p>{current.text}</p>
          </>
        ) : (
          <p className="muted">Нажмите «Вперёд», чтобы увидеть первый ход.</p>
        )}
        {ply === moves.length && <p className={css.done}>Линия пройдена</p>}
      </div>
      <MoveList moves={moves.map((m) => m.san)} current={ply - 1} onSelect={(p) => setPly(p + 1)} />
    </section>
  )
}
