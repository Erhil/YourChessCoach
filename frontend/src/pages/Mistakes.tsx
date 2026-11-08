import { useCallback, useEffect, useState } from 'react'
import {
  answerMistake,
  getMistakeStats,
  getNextMistake,
  type MistakeAnswer,
  type MistakeCard,
  type MistakeStats,
  type NextMistake,
} from '../api/mistakes'
import { Board, type Move } from '../components/Board'
import { CoachPanel } from '../components/CoachPanel'
import { ExerciseAnalysis } from '../components/ExerciseAnalysis'
import { lineArrows } from '../chess/arrows'
import { toFigurine, toUci } from '../chess/notation'
import { plural } from '../plural'
import css from './Mistakes.module.css'

const SOURCE = { game: 'Из вашей партии', puzzle: 'Из задачи', play: 'Из игры с тренером' }

function days(due: string): string {
  const n = Math.max(1, Math.round((Date.parse(due) - Date.now()) / 86_400_000))
  return `${n} ${plural(n, 'день', 'дня', 'дней')}`
}

/** «ещё 1 правильный ответ», «ещё 2 правильных ответа». */
function answersLeft(n: number): string {
  return n === 1 ? 'ещё 1 правильный ответ' : `ещё ${n} правильных ответа`
}

function feedback(a: MistakeAnswer, mine: string): string {
  if (!a.correct) return `Не тот ход. Лучше было ${toFigurine(a.best_san)}. Карточка вернётся сегодня.`
  // A move almost as good as the best one is also right; the best one is still named.
  const also = mine === a.best_uci ? '' : ` Ваш ход тоже хороший, лучший — ${toFigurine(a.best_san)}.`
  if (a.learned) return `Верно!${also} Три повторения пройдены. Следующее повторение через ${days(a.due_at)}.`
  return `Верно!${also} До трёх повторений: ${answersLeft(a.left)}. Следующее повторение через ${days(a.due_at)}.`
}

export default function Mistakes() {
  const [stats, setStats] = useState<MistakeStats | null>(null)
  const [card, setCard] = useState<MistakeCard | null>(null)
  const [next, setNext] = useState<NextMistake | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(false)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [mine, setMine] = useState('')
  const [ans, setAns] = useState<MistakeAnswer | null>(null)
  const [examining, setExamining] = useState(false)

  const load = useCallback(async () => {
    try {
      const [n, s] = await Promise.all([getNextMistake(), getMistakeStats()])
      setCard(n.card)
      setNext(n)
      setStats(s)
      setAns(null)
      setError(false)
    } catch {
      setError(true)
    }
    setLoaded(true)
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load sets state only after the fetch resolves
    void load()
  }, [load])

  const move = (m: Move): boolean => {
    if (!card || ans || busy) return false
    setBusy(true)
    const uci = toUci(m)
    setMine(uci)
    answerMistake(card.id, uci, card.review_version)
      .then((a) => {
        setAns(a)
        void getMistakeStats().then(setStats, () => {})
      })
      .catch(async () => {
        setNotice('Ответ мог сохраниться. Колода обновлена; продолжайте с доступной карточки.')
        await load()
      })
      .finally(() => setBusy(false))
    return true
  }

  const arrows = !card || !ans
    ? []
    : [
        ...(ans.correct ? [] : lineArrows(card.fen, [mine]).map((a) => ({ ...a, color: 'red' as const }))),
        ...lineArrows(card.fen, [ans.best_uci]),
      ]
  // Cards left today: the due ones, but not more than the daily limit allows.
  const left = next ? Math.max(0, Math.min(next.due, next.today.limit - next.today.reviewed)) : 0
  const limitReached = !!next && next.today.reviewed >= next.today.limit

  if (examining && card && ans) {
    return (
      <>
        <h1>Колода ошибок</h1>
        <ExerciseAnalysis
          fen={card.fen}
          continuation={[ans.best_uci]}
          orientation={card.side}
          onClose={() => setExamining(false)}
        />
      </>
    )
  }

  return (
    <>
      <h1>Колода ошибок</h1>
      {left > 0 && (
        <p data-testid="deck-today">
          <strong>{left} на сегодня</strong>
        </p>
      )}
      {!!stats?.learned && <p data-testid="deck-stats">Три повторения пройдены: {stats.learned}</p>}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">Не удалось связаться с сервером.</p>}
      {loaded && !card && !error && (
        <p className={css.status} data-testid="status">
          {limitReached
            ? `На сегодня всё: вы сделали ${next.today.reviewed} ${plural(next.today.reviewed, 'повторение', 'повторения', 'повторений')}. Возвращайтесь завтра.`
            : `На сегодня всё повторено. Карточек в колоде: ${stats?.total ?? 0}`}
        </p>
      )}
      {card && (
        <div className={css.layout}>
          <Board
            position={card.fen}
            orientation={card.side}
            canMove={!ans && !busy}
            onMove={move}
            arrows={arrows}
          />
          <div className={css.side}>
            <p className={css.status} data-testid="status" role="status">
              {!ans && 'Найдите лучший ход'}
              {ans && feedback(ans, mine)}
            </p>
            <p className="muted">{SOURCE[card.source]}</p>
            {card.played_san && <p data-testid="deck-played">В партии вы сыграли {toFigurine(card.played_san)}</p>}
            {ans && !ans.correct && ans.explanation && <CoachPanel text={ans.explanation.text} source={ans.explanation.source} />}
            <div className={css.controls}>
              {ans && (
                <button type="button" onClick={() => setExamining(true)}>
                  Разобрать варианты
                </button>
              )}
              <button type="button" onClick={() => void load()} disabled={!ans}>
                Следующая карточка
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
