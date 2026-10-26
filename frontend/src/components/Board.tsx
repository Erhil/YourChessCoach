import { Chess, type Square } from 'chess.js'
import { useState, type CSSProperties } from 'react'
import { Chessboard, defaultArrowOptions } from 'react-chessboard'
import type { Arrow } from '../chess/arrows'
import type { Quality } from '../chess/quality'
import { QualityBadge } from './QualityBadge'
import css from './Board.module.css'

export type Move = { from: string; to: string; promotion?: 'q' | 'r' | 'b' | 'n' }

type Props = {
  position: string
  orientation?: 'white' | 'black'
  canMove: boolean
  /** Returns true when the move was accepted. */
  onMove: (move: Move) => boolean
  lastMove?: { from: string; to: string } | null
  /** Extra square highlights: square -> CSS color. */
  highlights?: Record<string, string>
  /** Arrows (at most 3 are drawn); `step` fades them: 0 -> 100%, 1 -> 60%, 2+ -> 35%. */
  arrows?: Arrow[]
  /** A move-quality badge in the corner of a square. */
  badge?: { square: string; quality: Quality } | null
}

const PROMO = [
  ['q', '♕'],
  ['r', '♖'],
  ['b', '♗'],
  ['n', '♘'],
] as const

const RGB = { green: '40 170 70', red: '220 50 50' }
const ALPHA = [1, 0.6, 0.35]
const ARROW_OPTIONS = { ...defaultArrowOptions, opacity: 1 }

const LAST: CSSProperties = { background: 'rgb(255 214 0 / 40%)' }
const SELECTED: CSSProperties = { background: 'rgb(20 120 220 / 45%)' }
const TARGET: CSSProperties = {
  backgroundImage: 'radial-gradient(circle, rgb(20 120 220 / 55%) 22%, transparent 24%)',
}

export function Board({ position, orientation = 'white', canMove, onMove, lastMove, highlights, arrows = [], badge }: Props) {
  // Selection is tied to the position it was made in, so a new position clears it.
  const [sel, setSel] = useState<{ fen: string; square: string } | null>(null)
  const [promo, setPromo] = useState<{ fen: string; from: string; to: string } | null>(null)
  const selected = sel && sel.fen === position ? sel.square : null
  const pending = promo && promo.fen === position ? promo : null
  const turn = position.split(' ')[1] ?? 'w'

  const targets = (square: string): string[] =>
    new Chess(position).moves({ square: square as Square, verbose: true }).map((m) => m.to)

  const attempt = (from: string, to: string): boolean => {
    setSel(null)
    const piece = new Chess(position).get(from as Square)
    const lastRank = to.endsWith('8') || to.endsWith('1')
    if (piece?.type === 'p' && lastRank && targets(from).includes(to)) {
      setPromo({ fen: position, from, to })
      return false
    }
    return onMove({ from, to })
  }

  const onSquareClick = ({ square }: { square: string }) => {
    if (!canMove || pending) return
    // The piece comes from `position`: the board's own one is behind it while a change animates.
    const piece = new Chess(position).get(square as Square)
    if (selected && targets(selected).includes(square)) attempt(selected, square)
    else if (piece && piece.color === turn && square !== selected) setSel({ fen: position, square })
    else setSel(null)
  }

  const squareStyles: Record<string, CSSProperties> = {}
  if (lastMove) squareStyles[lastMove.from] = squareStyles[lastMove.to] = LAST
  for (const [sq, color] of Object.entries(highlights ?? {})) squareStyles[sq] = { background: color }
  if (selected) {
    squareStyles[selected] = SELECTED
    for (const t of targets(selected)) squareStyles[t] = { ...squareStyles[t], ...TARGET }
  }

  const drawn = arrows.slice(0, 3).map((a) => ({
    startSquare: a.from,
    endSquare: a.to,
    color: `rgb(${RGB[a.color]} / ${ALPHA[Math.min(a.step ?? 0, 2)]})`,
  }))

  return (
    <div className={css.wrap} data-arrows={drawn.length}
      data-arrow-squares={drawn.map((a) => a.startSquare + a.endSquare).join(' ')}
    >
      <Chessboard
        options={{
          position,
          boardOrientation: orientation,
          allowDragging: canMove && !pending,
          canDragPiece: ({ piece }) => canMove && piece.pieceType[0] === turn,
          onPieceDrop: ({ sourceSquare, targetSquare }) =>
            targetSquare ? attempt(sourceSquare, targetSquare) : false,
          onSquareClick,
          squareStyles,
          squareRenderer: ({ square, children }) => (
            <div style={{ width: '100%', height: '100%', ...squareStyles[square] }}>
              {children}
              {badge?.square === square && <QualityBadge kind={badge.quality} className={css.badge} />}
            </div>
          ),
          arrows: drawn,
          arrowOptions: ARROW_OPTIONS,
          allowDrawingArrows: false,
          animationDurationInMs: 150,
        }}
      />
      {pending && (
        <div className={css.promo} role="dialog" aria-label="Превращение пешки">
          <div className={css.promoBox}>
            {PROMO.map(([p, glyph]) => (
              <button
                key={p}
                type="button"
                data-promotion={p}
                aria-label={{ q: 'Ферзь', r: 'Ладья', b: 'Слон', n: 'Конь' }[p]}
                onClick={() => {
                  setPromo(null)
                  onMove({ from: pending.from, to: pending.to, promotion: p })
                }}
              >
                {glyph}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
