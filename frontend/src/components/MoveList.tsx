import { toFigurine } from '../chess/notation'
import type { Quality } from '../chess/quality'
import { QualityBadge } from './QualityBadge'
import css from './MoveList.module.css'

type Props = {
  /** Moves in SAN, white's first move first. */
  moves: string[]
  /** Mark per ply (`?!`, `?`, `??`), appended to the move. */
  marks?: string[]
  /** Quality badge per ply, shown after the move. */
  badges?: (Quality | undefined)[]
  /** Ply index to highlight; the last move by default. */
  current?: number
  /** When set, moves are buttons that report their ply index. */
  onSelect?: (ply: number) => void
}

export function MoveList({ moves, marks, badges, current, onSelect }: Props) {
  const pairs: string[][] = []
  for (let i = 0; i < moves.length; i += 2) pairs.push(moves.slice(i, i + 2))
  const active = current ?? moves.length - 1

  return (
    <ol className={css.list} aria-label="Ходы партии">
      {pairs.map((pair, n) => (
        <li key={n} className={css.pair}>
          <span className={css.num}>{n + 1}.</span>
          {pair.map((san, k) => {
            const ply = n * 2 + k
            const on = ply === active
            const props = {
              className: `${css.move} ${on ? css.last : ''}`,
              'data-last': on ? 'true' : undefined,
            }
            const text = toFigurine(san) + (marks?.[ply] ?? '')
            const badge = badges?.[ply]
            return onSelect ? (
              <button key={k} type="button" {...props} onClick={() => onSelect(ply)}>
                {text}
                {badge && <QualityBadge kind={badge} />}
              </button>
            ) : (
              <span key={k} {...props}>
                {text}
                {badge && <QualityBadge kind={badge} />}
              </span>
            )
          })}
        </li>
      ))}
    </ol>
  )
}
