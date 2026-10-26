import { Chess } from 'chess.js'
import { useEffect, useRef, useState } from 'react'
import { coachMove, type LessonSegment } from '../api/client'
import { Board, type Move } from '../components/Board'
import { sleep, toFigurine, toUci } from '../chess/notation'
import css from './LessonPosition.module.css'

type Block = Extract<LessonSegment, { type: 'chess' }>
type Phase = 'play' | 'opp' | 'check' | 'done' | 'solution'

const bare = (san: string) => san.replace(/[+#]$/, '')
const WRONG = 'Не совсем. Попробуйте ещё раз.'

type Props = { index: number; block: Block; solved: boolean; onSolved: (index: number) => void }

export function LessonPosition({ index, block, solved, onSolved }: Props) {
  const { fen, solution } = block
  const [played, setPlayed] = useState<string[]>([])
  const [phase, setPhase] = useState<Phase>('play')
  const [msg, setMsg] = useState('')
  const [hint, setHint] = useState(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const chess = new Chess(fen)
  for (const san of played) chess.move(san)
  const color = new Chess(fen).turn() === 'w' ? 'white' : 'black'
  const last = chess.history({ verbose: true }).at(-1)
  const k = played.length

  const finish = () => {
    setPhase('done')
    setMsg('Верно!')
    onSolved(index)
  }

  const checkAlternative = async (san: string, uci: string) => {
    setPhase('check')
    setMsg('Проверяю…')
    const ok = await coachMove(fen, uci).then(
      (r) => r.facts.classification === 'best',
      () => false,
    )
    if (!alive.current) return
    if (ok) {
      setPlayed([san])
      setPhase('done')
      setMsg(`Тоже верно! В уроке разобран ход ${toFigurine(solution[0])}.`)
      onSolved(index)
    } else {
      setPhase('play')
      setMsg(WRONG)
    }
  }

  const move = (m: Move): boolean => {
    if (phase !== 'play') return false
    const test = new Chess(chess.fen())
    let made
    try {
      made = test.move(m)
    } catch {
      return false
    }
    // Any checkmate is a correct answer, also when the lesson line is longer.
    if (bare(made.san) !== bare(solution[k]) && !test.isCheckmate()) {
      if (k === 0) {
        void checkAlternative(made.san, toUci(made))
        return false
      }
      setMsg(WRONG)
      return false
    }
    setMsg('')
    const reply = solution[k + 1]
    setPlayed([...played, made.san])
    if (test.isCheckmate() || !reply) finish()
    else {
      setPhase('opp')
      void sleep(400).then(() => {
        if (!alive.current) return
        setPlayed((p) => [...p, reply])
        if (k + 2 >= solution.length) finish()
        else setPhase('play')
      })
    }
    return true
  }

  const showSolution = async () => {
    setPhase('solution')
    setMsg('')
    for (const san of solution.slice(k)) {
      await sleep(700)
      if (!alive.current) return
      setPlayed((p) => [...p, san])
    }
  }

  const shown = phase === 'solution' || phase === 'done' ? played : []
  return (
    <section className={css.box} data-testid={`position-${index}`}>
      <p className={css.task}>
        {block.task} {solved && <span className={css.mark}>Решено</span>}
      </p>
      <Board
        position={chess.fen()}
        orientation={color}
        canMove={phase === 'play'}
        onMove={move}
        lastMove={last ? { from: last.from, to: last.to } : null}
      />
      <p className={css.status} role="status" data-testid="status">
        {msg}
      </p>
      {hint && <p>Подсказка: {block.hint}</p>}
      {shown.length > 0 && <p>Ходы: {shown.map(toFigurine).join(' ')}</p>}
      <div className={css.buttons}>
        <button type="button" onClick={() => setHint(true)}>
          Подсказка
        </button>
        {phase === 'play' && (
          <button type="button" onClick={showSolution}>
            Показать решение
          </button>
        )}
      </div>
    </section>
  )
}
