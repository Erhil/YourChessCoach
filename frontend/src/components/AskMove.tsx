import { useState } from 'react'
import { askAboutMove, type CoachQuestion } from '../api/client'
import { lineArrows, type Arrow } from '../chess/arrows'
import css from './AskMove.module.css'

const BUTTONS: [CoachQuestion, string][] = [
  ['why', 'Почему ход плохой?'],
  ['threat', 'Что угрожает?'],
  ['better', 'Что надо было делать?'],
]
const BAD = ['inaccuracy', 'mistake', 'blunder']

type Props = {
  fen: string
  move: string
  /** Of the move: «why is the move bad» is offered only for an inaccuracy, a mistake or a blunder. */
  classification?: string
  onArrows?: (arrows: Arrow[], fen: string) => void
}

export function AskMove({ fen, move, classification, onArrows }: Props) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [reply, setReply] = useState<string | null>(null)

  const ask = (question: CoachQuestion, free?: string) => {
    if (busy) return
    setBusy(true)
    askAboutMove(fen, move, question, free)
      .then(
        (r) => {
          setReply(r.answer ?? r.reason ?? 'Тренер сейчас недоступен')
          if (r.answer && r.line) {
            // «better» is the student's line (green, then the replies); the other answers show the opponent's move.
            const arrows = lineArrows(r.line.fen, r.line.moves)
            onArrows?.(
              question === 'better' ? arrows : arrows.map((a) => ({ ...a, color: 'red' as const })),
              r.line.fen,
            )
          }
        },
        () => setReply('Тренер сейчас недоступен'),
      )
      .finally(() => setBusy(false))
  }

  return (
    <div className={css.ask}>
      <div className={css.buttons}>
        {BUTTONS.filter(([q]) => q !== 'why' || (classification && BAD.includes(classification))).map(([q, label]) => (
          <button key={q} type="button" disabled={busy} onClick={() => ask(q)}>
            {label}
          </button>
        ))}
      </div>
      <form
        className={css.free}
        onSubmit={(e) => {
          e.preventDefault()
          if (text.trim()) ask('free', text.trim())
        }}
      >
        <input
          value={text}
          maxLength={300}
          placeholder="Свой вопрос…"
          aria-label="Свой вопрос тренеру"
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" disabled={busy || !text.trim()}>
          Спросить
        </button>
      </form>
      {busy && <p className="muted">Тренер думает…</p>}
      {reply && !busy && <p role="status">{reply}</p>}
    </div>
  )
}
