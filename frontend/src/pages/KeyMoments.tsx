import { CoachPanel } from '../components/CoachPanel'
import { CLASS_WORD, toFigurine } from '../chess/notation'
import type { Arrow } from '../chess/arrows'
import type { KeyMoment } from '../api/review'
import css from './Review.module.css'

export const MARKS: Record<string, string> = { inaccuracy: '?!', mistake: '?', blunder: '??' }

type Props = { moments: KeyMoment[]; onShow: (m: KeyMoment) => void; onAsk: (m: KeyMoment, arrows: Arrow[]) => void }

export function KeyMoments({ moments, onShow, onAsk }: Props) {
  if (moments.length === 0) return <p>Явных ошибок не найдено. Хорошая партия!</p>
  return (
    <ol className={css.moments} aria-label="Ключевые моменты">
      {moments.map((m) => (
        <li key={m.ply} data-testid="key-moment">
          <h3>
            {Math.ceil(m.ply / 2)}
            {m.ply % 2 ? '.' : '...'} {toFigurine(m.san)}
            {MARKS[m.classification]} — {CLASS_WORD[m.classification]}
          </h3>
          <CoachPanel
            text={m.explanation.text}
            source={m.explanation.source}
            lesson={m.facts.lesson}
            fen={m.facts.fen_before}
            move={m.facts.player_move.uci}
            classification={m.classification}
            onArrows={(a) => onAsk(m, a)}
          />
          <button type="button" onClick={() => onShow(m)}>
            Показать позицию
          </button>
        </li>
      ))}
    </ol>
  )
}
