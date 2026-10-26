import { useState } from 'react'
import { askLesson } from '../api/client'
import { CoachPanel } from '../components/CoachPanel'
import css from './AskCoach.module.css'

type Result = { answer: string | null; reason: string | null }

export function AskCoach({ slug, positions }: { slug: string; positions: number }) {
  const [question, setQuestion] = useState('')
  const [position, setPosition] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Result | null>(null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const q = question.trim()
    if (!q || busy) return
    setBusy(true)
    setResult(null)
    askLesson(slug, q, position === '' ? null : Number(position))
      .then(setResult, () => setResult({ answer: null, reason: 'Тренер сейчас недоступен' }))
      .finally(() => setBusy(false))
  }

  return (
    <form className={css.ask} onSubmit={submit}>
      <label>
        Ваш вопрос тренеру
        <textarea value={question} maxLength={300} rows={3} onChange={(e) => setQuestion(e.target.value)} />
      </label>
      {positions > 0 && (
        <label>
          О какой позиции?
          <select value={position} onChange={(e) => setPosition(e.target.value)}>
            <option value="">Ни о какой</option>
            {Array.from({ length: positions }, (_, i) => (
              <option key={i} value={i}>
                Позиция {i + 1}
              </option>
            ))}
          </select>
        </label>
      )}
      <button type="submit" disabled={busy || !question.trim()}>
        Спросить
      </button>
      {busy && <p className="muted">Тренер думает…</p>}
      {result?.answer && <CoachPanel text={result.answer} source="llm" />}
      {result && !result.answer && <p className="muted">{result.reason}</p>}
    </form>
  )
}
