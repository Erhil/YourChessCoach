import { Chess } from 'chess.js'
import { useEffect, useMemo, useRef, useState } from 'react'
import { analyze, coachMove, type Analysis, type CoachResult } from '../api/client'
import { splitUci, toFigurine, toUci } from '../chess/notation'
import { Board, type Move } from './Board'
import { CoachPanel } from './CoachPanel'
import css from './ExerciseAnalysis.module.css'

type Props = {
  fen: string
  setupMove?: string
  continuation: string[]
  orientation: 'white' | 'black'
  onClose: () => void
}

export function ExerciseAnalysis({ fen, setupMove, continuation, orientation, onClose }: Props) {
  const [line, setLine] = useState(continuation)
  const [ply, setPly] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const { chess, last } = useMemo(() => {
    const board = new Chess(fen)
    if (setupMove) board.move(splitUci(setupMove))
    let last
    for (const uci of line.slice(0, ply)) last = board.move(splitUci(uci))
    return { chess: board, last }
  }, [fen, setupMove, line, ply])
  const position = chess.fen()
  const mate = chess.isCheckmate()
  const terminal = mate || chess.isDraw()
  const [engine, setEngine] = useState<{ board: Chess; result: Analysis | null }>()
  const [requestedReview, setRequestedReview] = useState<Chess>()
  const [coach, setCoach] = useState<{ board: Chess; result: CoachResult | null }>()
  const alternatives = engine?.board === chess ? engine.result : undefined
  const review = coach?.board === chess ? coach.result : undefined
  const before = last?.before
  const played = last && toUci(last)

  useEffect(() => heading.current?.focus(), [])

  useEffect(() => {
    if (terminal) return
    let active = true
    const timer = window.setTimeout(() => {
      void analyze(position, 300, 3).then(
        (result) => { if (active) setEngine({ board: chess, result }) },
        () => { if (active) setEngine({ board: chess, result: null }) },
      )
    }, 200)
    return () => { active = false; window.clearTimeout(timer) }
  }, [chess, position, terminal])

  useEffect(() => {
    if (!before || !played || requestedReview !== chess) return
    let active = true
    void coachMove(before, played, 5).then(
      (result) => { if (active) setCoach({ board: chess, result }) },
      () => { if (active) setCoach({ board: chess, result: null }) },
    )
    return () => { active = false }
  }, [before, chess, played, requestedReview])

  function move(candidate: Move | string, variation?: string[]): boolean {
    if (terminal) return false
    try {
      const uci = toUci(new Chess(position).move(typeof candidate === 'string' ? splitUci(candidate) : candidate))
      if (variation || uci !== line[ply]) setLine([...line.slice(0, ply), ...(variation ?? [uci])])
      setPly(ply + 1)
      return true
    } catch {
      return false
    }
  }

  const turn = chess.turn() === 'w' ? 'Ход белых' : 'Ход чёрных'

  return (
    <section aria-labelledby="exercise-analysis-title">
      <h2 id="exercise-analysis-title" ref={heading} tabIndex={-1}>Разбор вариантов</h2>
      <div className={css.layout}>
        <Board key={position} position={position} orientation={orientation} canMove={!terminal} onMove={move} lastMove={last} />
        <div className={css.side}>
          <div className={css.controls}>
            <button type="button" onClick={() => setPly(ply - 1)} disabled={ply === 0}>Назад</button>
            <button type="button" onClick={() => move(line[ply])} disabled={terminal || ply >= line.length}>
              Вперёд
            </button>
            <button type="button" onClick={onClose}>Закрыть разбор</button>
          </div>
          <p role="status" aria-label="Позиция в разборе">
            {last ? `Ход ${ply}. ${toFigurine(last.san)}. ` : 'Начальная позиция. '}
            {mate ? 'Мат.' : terminal ? 'Ничья.' : turn}
          </p>
          {!terminal && (
            <div>
              <h3>Варианты Stockfish</h3>
              {alternatives === undefined && <p className="muted">Движок ищет варианты…</p>}
              {alternatives === null && <p>Варианты сейчас недоступны.</p>}
              {alternatives?.lines.length === 0 && <p>Движок не нашёл вариантов.</p>}
              {alternatives?.lines.map(({ rank, pv_san, pv_uci }) => pv_uci[0] && pv_san[0] && (
                <div key={rank} className={css.variant}>
                  <button type="button" onClick={() => move(pv_uci[0], pv_uci)}>
                    Сыграть {toFigurine(pv_san[0])}
                  </button>
                  {pv_san.length > 1 && <span>{pv_san.slice(1, 5).map(toFigurine).join(' ')}</span>}
                </div>
              ))}
            </div>
          )}
          {last && (
            <div>
              <h3>Объяснение хода {toFigurine(last.san)}</h3>
              {requestedReview !== chess && (
                <button type="button" onClick={() => setRequestedReview(chess)}>Объяснить ход</button>
              )}
              {requestedReview === chess && review === undefined && <p className="muted">Тренер разбирает ход…</p>}
              {(review === null || (review && !review.explanation)) && <p>Объяснение сейчас недоступно.</p>}
              {review?.explanation && (
                <CoachPanel
                  key={before + ' ' + played}
                  text={review.explanation.text}
                  source={review.explanation.source}
                  fen={before}
                  move={played}
                  classification={review.facts.classification}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
