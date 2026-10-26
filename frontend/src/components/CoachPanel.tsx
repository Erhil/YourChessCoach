import { Link } from 'react-router-dom'
import type { Arrow } from '../chess/arrows'
import { AskMove } from './AskMove'
import css from './CoachPanel.module.css'

type Props = {
  text: string
  source?: string
  lesson?: { slug: string; title: string } | null
  onShow?: () => void
  /** With `fen` (before the move) and `move` (UCI) the panel offers questions about the move. */
  fen?: string
  move?: string
  classification?: string
  onArrows?: (arrows: Arrow[]) => void
}

export function CoachPanel({ text, source, lesson, onShow, fen, move, classification, onArrows }: Props) {
  return (
    <aside className={css.panel} aria-label="Тренер">
      <p>{text}</p>
      {source && <small className={css.source}>{source === 'llm' ? 'тренер (ИИ)' : 'тренер (шаблон)'}</small>}
      {lesson && <Link to={`/lessons/${lesson.slug}`}>Урок: {lesson.title}</Link>}
      {onShow && (
        <button type="button" className={css.show} onClick={onShow}>
          Показать на доске
        </button>
      )}
      {fen && move && <AskMove fen={fen} move={move} classification={classification} onArrows={onArrows} />}
    </aside>
  )
}
