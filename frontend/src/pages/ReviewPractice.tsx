import { Chess } from 'chess.js'
import { useLayoutEffect, useRef, useState } from 'react'
import { coachMove } from '../api/client'
import { HttpError } from '../api/http'
import type { KeyMoment } from '../api/review'
import { sessionKey } from '../auth/session'
import { splitUci, toFigurine } from '../chess/notation'
import { PracticeBoard } from '../components/PracticeBoard'
import { newAttemptId } from '../puzzles/resultQueue'
import css from './Review.module.css'

type Result = { accepted: boolean; line: string[]; text: string }
type FirstAttempt = { uci: string; at: number; assisted: boolean; accepted?: boolean }
type PracticeRecord = { revealed?: boolean; first?: FirstAttempt; last?: Result }
type Attempt = Omit<FirstAttempt, 'accepted'> & {
  id: string
  retryOf?: string
  result?: Result & { checkedAt: number }
}

function read<T>(key: string): T | null {
  try {
    return JSON.parse(localStorage.getItem(key) ?? 'null')
  } catch {
    return null
  }
}

function save(key: string, value: true | Attempt) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // The mounted exercise still keeps its progress when storage is unavailable.
  }
}

const recordKey = (game: number, ply: number) => sessionKey(`review.practice.${game}.${ply}`)
const attemptPrefix = (key: string) => `${key}:attempt:`
const now = () => performance.timeOrigin + performance.now()

function load(key: string, local: Attempt[] = [], locallyRevealed = false) {
  const legacy = read<PracticeRecord>(key)
  const revealed = locallyRevealed || Boolean(legacy?.revealed || read<true>(`${key}:revealed`))
  const prefix = attemptPrefix(key)
  const attempts = new Map<string, Attempt>()
  try {
    for (let index = 0; index < localStorage.length; index++) {
      const name = localStorage.key(index)
      if (!name?.startsWith(prefix)) continue
      const attempt = read<Attempt>(name)
      if (attempt) attempts.set(attempt.id, attempt)
    }
  } catch {
    // The local attempts still work when storage is unavailable.
  }
  for (const attempt of local) attempts.set(attempt.id, attempt)
  const ordered = [...attempts.values()].sort((a, b) => a.at - b.at || a.id.localeCompare(b.id))
  const moves = ordered.filter((attempt) => !attempt.retryOf)
  const first = legacy?.first ?? moves[0]
  const firstId = legacy?.first ? 'legacy' : moves[0]?.id
  const results = new Map<string, NonNullable<Attempt['result']>>()
  for (const attempt of ordered) {
    const id = attempt.retryOf ?? attempt.id
    const previous = results.get(id)
    if (attempt.result && (!previous || attempt.result.checkedAt < previous.checkedAt)) {
      results.set(id, attempt.result)
    }
  }
  const completed: (Result | undefined)[] = moves.slice().reverse().map(({ id }) => results.get(id))
  completed.push(results.get('legacy') ?? legacy?.last)
  const last = completed.find((result) => result?.accepted) ?? completed.find(Boolean)
  const checkedFirst = first && firstId
    ? { ...first, accepted: legacy?.first?.accepted ?? results.get(firstId)?.accepted }
    : undefined
  const unchecked = legacy?.first && checkedFirst?.accepted === undefined
    ? { uci: legacy.first.uci, id: 'legacy' }
    : moves.find(({ id }) => !results.has(id))
  return { revealed, first: checkedFirst, last, unchecked }
}

export function markReviewRevealed(game: number, ply: number) {
  const key = recordKey(game, ply)
  save(`${key}:revealed`, true)
}

export function ReviewPractice({
  game, moment, side, onExit,
}: { game: number; moment: KeyMoment; side: 'white' | 'black'; onExit: () => void }) {
  const [key] = useState(() => recordKey(game, moment.ply))
  const [record, setRecord] = useState(() => load(key))
  const [showLine, setShowLine] = useState(() => Boolean(record.revealed && !record.last?.accepted))
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const request = useRef<symbol | null>(null)
  const attempts = useRef<Attempt[]>([])
  const section = useRef<HTMLElement>(null)
  const fen = moment.facts.fen_before
  const best = moment.facts.best_move?.uci

  useLayoutEffect(() => {
    section.current?.scrollIntoView({ block: 'start' })
    return () => { request.current = null }
  }, [])

  async function submit(uci: string, retryOf?: string) {
    if (request.current || (!retryOf && (showLine || record.last?.accepted || record.unchecked))) return
    const id = Symbol()
    request.current = id
    const current = load(key, attempts.current, record.revealed)
    const attempt = {
      id: newAttemptId(), uci, at: now(),
      assisted: current.revealed, retryOf,
    }
    const attemptKey = attemptPrefix(key) + attempt.id
    attempts.current.push(attempt)
    // Only this request can complete its storage entry. Other tabs have separate entries.
    save(attemptKey, attempt)
    setRecord(load(key, attempts.current, record.revealed))
    setBusy(true)
    setFailed(null)
    try {
      const result = await coachMove(fen, uci, 1)
      if (request.current !== id) return
      const { classification, best_move, best_line, refutation } = result.facts
      const good = classification === 'best' || classification === 'good'
      const accepted = good || uci === best || uci === best_move?.uci
      const line = !good && uci === best ? moment.facts.best_line.length ? moment.facts.best_line : [uci]
        : uci === best_move?.uci && best_line?.length ? best_line
        : [uci, ...(refutation ?? [])]
      const last = { accepted, line: accepted ? line : [], text: good ? result.explanation?.text ?? '' : '' }
      const checked = { ...attempt, result: { ...last, checkedAt: now() } }
      attempts.current[attempts.current.length - 1] = checked
      save(attemptKey, checked)
      const updated = load(key, attempts.current, record.revealed)
      setRecord(updated)
      if (!showLine && !current.last?.accepted) setStep(updated.last?.accepted ? 1 : 0)
    } catch (error) {
      if (request.current !== id) return
      const message = error instanceof HttpError && error.status === 503
        ? 'Stockfish сейчас недоступен. Повторите проверку.'
        : 'Не удалось проверить ход. Повторите проверку.'
      setFailed(message)
    } finally {
      if (request.current === id) {
        request.current = null
        setBusy(false)
      }
    }
  }

  const chess = new Chess(fen)
  const line = showLine
    ? moment.facts.best_line.length ? moment.facts.best_line : best ? [best] : []
    : record.last?.line ?? []
  const moves = []
  for (const move of line) {
    try {
      moves.push(chess.move(/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(move) ? splitUci(move) : move))
    } catch {
      break
    }
  }
  const ply = Math.min(step, moves.length)
  const current = moves[ply - 1]
  const canTry = !busy && !showLine && !record.last?.accepted
  const retry = record.unchecked

  return (
    <section className={css.practice} aria-label="Самостоятельная попытка" ref={section}>
      <button type="button" onClick={() => {
        request.current = null
        onExit()
      }}>Вернуться к разбору</button>
      <PracticeBoard
        position={current?.after ?? fen}
        orientation={side}
        canMove={canTry && !retry}
        onMove={submit}
        prompt={`Найдите хороший ход за ${side === 'white' ? 'белых' : 'чёрных'}.`}
        lastMove={current}
        feedbackClassName={css.practiceFeedback}
        onReveal={canTry ? () => {
          if (request.current) return
          save(`${key}:revealed`, true)
          setRecord(load(key, attempts.current, true))
          setShowLine(true)
          setStep(0)
        } : undefined}
        feedback={
          <>
            {busy && <p role="status">Stockfish проверяет ход…</p>}
            {failed && <p role="alert">{failed}</p>}
            {retry && !busy && (
              <button type="button" onClick={() => void submit(retry.uci, retry.id)}>Повторить проверку хода</button>
            )}
            {record.first && (
              <p>
                {record.first.assisted ? 'Первая попытка с помощью' : 'Первая самостоятельная попытка'}
                {record.first.accepted === undefined ? ' ещё не проверена.' : record.first.accepted ? ' засчитана.' : ' не засчитана.'}
              </p>
            )}
            {!busy && !showLine && record.last && (
              <div role="status">
                <p>{record.last.accepted ? 'Ход засчитан.' : 'Stockfish нашёл ход сильнее. Попробуйте ещё раз.'}</p>
                {record.last.accepted && record.last.text && <p>{record.last.text}</p>}
              </div>
            )}
            {(showLine || record.last?.accepted) && (
              <>
                <p>{showLine ? moment.explanation.text : 'Продолжение вашего хода.'}</p>
                {moves.length > 0 && (
                  <div className={css.row}>
                    <button type="button" disabled={ply === 0} onClick={() => setStep(ply - 1)}>Предыдущий ход решения</button>
                    <button type="button" disabled={ply === moves.length} onClick={() => setStep(ply + 1)}>Следующий ход решения</button>
                  </div>
                )}
                {current && <p role="status">{toFigurine(current.san)} · {ply} из {moves.length}</p>}
                {showLine && !record.last?.accepted && (
                  <button type="button" onClick={() => {
                    setShowLine(false)
                    setStep(0)
                  }}>Попробовать с помощью</button>
                )}
              </>
            )}
          </>
        }
      />
    </section>
  )
}
