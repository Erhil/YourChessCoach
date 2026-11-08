import { Chess } from 'chess.js'
import type { ReactNode } from 'react'
import { toUci } from '../chess/notation'
import { Board, type Move } from './Board'

type Props = {
  position: string
  orientation: 'white' | 'black'
  canMove: boolean
  onMove: (uci: string) => void
  prompt: string
  feedback?: ReactNode
  feedbackClassName?: string
  onReveal?: () => void
  lastMove?: { from: string; to: string } | null
}

export function PracticeBoard({ position, orientation, canMove, onMove, prompt, feedback, feedbackClassName, onReveal, lastMove }: Props) {
  const attempt = (move: Move) => {
    if (!canMove) return false
    try {
      new Chess(position).move(move)
    } catch {
      return false
    }
    onMove(toUci(move))
    // The caller changes the position after it verifies the attempt.
    return false
  }

  const controls = (
    <>
      {feedback}
      {onReveal && <button type="button" onClick={onReveal}>Показать решение</button>}
    </>
  )
  return (
    <>
      <p>{prompt}</p>
      <Board position={position} orientation={orientation} canMove={canMove} onMove={attempt} lastMove={lastMove} />
      {feedbackClassName ? <div className={feedbackClassName}>{controls}</div> : controls}
    </>
  )
}
