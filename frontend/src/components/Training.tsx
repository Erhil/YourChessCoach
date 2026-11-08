import { Chess } from 'chess.js'
import { useCallback, useEffect, useRef, useState } from 'react'
import { HttpError } from '../api/http'
import { getTraining, writeTraining, type TrainingIntent, type TrainingSession, type TrainingStatus, type TrainingWrite } from '../api/training'
import { sessionLogin } from '../auth/session'
import { splitUci, toFigurine } from '../chess/notation'
import { PracticeBoard } from './PracticeBoard'
import css from './Training.module.css'
import today from './Today.module.css'

function pendingWrites(prefix: string, login: string) {
  const writes: { key: string; payload: TrainingWrite }[] = []
  for (let index = 0; index < localStorage.length; index++) {
    const key = localStorage.key(index)
    if (!key?.startsWith(prefix)) continue
    const raw = localStorage.getItem(key)
    if (raw === null) continue
    const payload = JSON.parse(raw) as TrainingWrite
    if (payload.expected_login !== login || key !== prefix + payload.client_id) throw new Error('Invalid training write')
    writes.push({ key, payload })
  }
  return writes
}

export default function Training({ login }: { login: string }) {
  const [status, setStatus] = useState<TrainingStatus>()
  const [busy, setBusy] = useState(true)
  const [failure, setFailure] = useState<string>()
  const [notice, setNotice] = useState<string>()
  const request = useRef<symbol | null>(null)
  const prefix = `chess-training:${encodeURIComponent(login)}:`

  const sync = useCallback(async (intent?: TrainingIntent) => {
    if (request.current || sessionLogin() !== login) return
    const id = Symbol()
    request.current = id
    const current = () => request.current === id && sessionLogin() === login
    setBusy(true)
    setFailure(undefined)
    setNotice(undefined)
    let storage = true
    try {
      const writes = pendingWrites(prefix, login)
      let message = intent && writes.length > 0
        ? 'Отправлено ожидающее действие. Проверьте сохранённый шаг.'
        : undefined
      if (intent && writes.length === 0) {
        const client_id = Array.from(crypto.getRandomValues(new Uint32Array(4)), (part) => part.toString(16).padStart(8, '0')).join('')
        const payload = { ...intent, client_id, expected_login: login }
        const key = prefix + client_id
        localStorage.setItem(key, JSON.stringify(payload))
        writes.push({ key, payload })
      }
      let authoritative: TrainingStatus | undefined
      for (const { key, payload } of writes) {
        storage = false
        authoritative = undefined
        try {
          await writeTraining(payload)
        } catch (error) {
          if (!current()) return
          if (!(error instanceof HttpError) || ![404, 409, 422].includes(error.status)) throw error
          // A rejected write can be removed only after a read for the same owner succeeds.
          authoritative = await getTraining(login)
          message = error.status === 409 ? 'Занятие уже обновилось. Показан сохранённый шаг.'
            : error.status === 422 ? 'Сервер отклонил действие. Проверьте сохранённый шаг.' : error.message
        }
        if (!current()) return
        storage = true
        // Each operation owns its key. A late reply cannot remove another tab's newer write.
        localStorage.removeItem(key)
      }
      storage = false
      const saved = authoritative ?? await getTraining(login)
      if (!current()) return
      setStatus(saved)
      setNotice(message)
    } catch (error) {
      if (!current()) return
      if (error instanceof HttpError && error.status === 403) {
        setStatus(undefined)
        setFailure('В другой вкладке открыт другой профиль. Войдите в этот профиль, чтобы продолжить занятие.')
      } else {
        setFailure(storage
          ? 'Хранилище браузера недоступно. Действие нельзя сохранить для повтора. Проверьте доступ к хранилищу.'
          : error instanceof HttpError && error.status === 503
            ? 'Stockfish сейчас недоступен. Повторите отправку.'
            : 'Не удалось связаться с сервером. Повторите отправку.')
      }
    } finally {
      if (request.current === id) {
        request.current = null
        setBusy(false)
      }
    }
  }, [login, prefix])

  useEffect(() => {
    let mounted = true
    const refresh = () => { void sync() }
    void Promise.resolve().then(() => { if (mounted) refresh() })
    window.addEventListener('online', refresh)
    return () => {
      mounted = false
      request.current = null
      window.removeEventListener('online', refresh)
    }
  }, [sync])

  const session = status?.session
  const active = session && session.state !== 'done'
  const blocked = busy || Boolean(failure)

  return (
    <section aria-label="Занятие на пять минут" className={today.card}>
      <h2>Занятие на пять минут</h2>
      {busy && <p role="status">Загружаем занятие…</p>}
      {failure && <p role="alert">{failure}</p>}
      {failure && <button type="button" onClick={() => void sync()}>Повторить отправку</button>}
      {notice && <p role="status">{notice}</p>}
      {session?.notice && <p>{session.notice}</p>}
      {active && session.position && (
        <Exercise
          key={`${session.id}:${session.step}`}
          session={session}
          position={session.position}
          blocked={blocked}
          act={(action, uci) => void sync({ session: session.id, version: session.version, action, uci })}
        />
      )}
      {session?.state === 'done' && (
        <div role="status">
          <h3>{session.kind === 'delayed' ? 'Итог проверки после перерыва' : 'Итог занятия'}</h3>
          <p>Самостоятельно: {session.counts.independent.correct} из {session.counts.independent.answered} верно.</p>
          <p>С помощью: {session.counts.assisted.correct} из {session.counts.assisted.answered} верно.</p>
          <p>Без ответа: {session.counts.unfinished} из {session.counts.assigned}.</p>
          <p>Незнакомые позиции в занятии: {session.new_positions} из {session.counts.assigned}.</p>
          {session.delay_days !== null && <p>Перерыв: {session.delay_days.toLocaleString('ru', { maximumFractionDigits: 1 })} дн.</p>}
          {session.difficulty && <p>Диапазон рейтинга упражнений: {session.difficulty.min}–{session.difficulty.max}.</p>}
        </div>
      )}
      {!active && status && (
        <>
          {!session && <p>Решите несколько позиций в своём темпе.</p>}
          <div className={css.controls}>
            <button type="button" disabled={blocked} onClick={() => void sync({ kind: 'practice' })}>
              {session ? 'Начать новое занятие' : 'Начать занятие'}
            </button>
            {status.delayed_available && (
              <button type="button" disabled={blocked} onClick={() => void sync({ kind: 'delayed' })}>
                Пройти проверку после перерыва
              </button>
            )}
          </div>
          {!status.delayed_available && status.delayed_notice && <p className="muted">{status.delayed_notice}</p>}
        </>
      )}
    </section>
  )
}

function Exercise({ session, position, blocked, act }: {
  session: TrainingSession
  position: NonNullable<TrainingSession['position']>
  blocked: boolean
  act: (action: 'move' | 'hint' | 'reveal' | 'next' | 'finish', uci?: string) => void
}) {
  const [lineStep, setLineStep] = useState(0)
  const question = session.state === 'question'
  const task = position.source === 'game' ? 'хороший' : 'сильнейший'
  const side = position.side === 'white' ? 'белых' : 'чёрных'
  const feedback = session.feedback
  const originalMove = feedback?.original_uci
    ? new Chess(position.fen).move(splitUci(feedback.original_uci))
    : null
  const chess = new Chess(position.fen)
  const moves = []
  for (const uci of feedback?.line ?? []) moves.push(chess.move(splitUci(uci)))
  const current = moves[lineStep - 1]
  return (
    <div className={css.exercise}>
      <div className={css.board}>
        <p>Позиция {session.step} из {session.total}</p>
        <PracticeBoard
          position={current?.after ?? position.fen}
          orientation={position.side}
          canMove={question && !blocked}
          onMove={(uci) => act('move', uci)}
          prompt={question ? `Найдите ${task} ход за ${side}.` : 'Проверенное продолжение'}
          lastMove={current}
        />
      </div>
      <div>
        {session.kind === 'delayed' && question
          ? <p>Проверка после перерыва</p>
          : <p>{position.source === 'game' ? 'Позиция из вашей партии'
            : session.kind === 'practice' && session.step === 1 ? 'Базовое упражнение'
              : 'Незнакомое упражнение'}</p>}
        {position.rating !== null && (session.kind !== 'delayed' || !question) && <p>Рейтинг упражнения: {position.rating}.</p>}
        {question ? (
          <>
            {position.hint && <p role="status">{position.hint}</p>}
            <div className={css.controls}>
              {session.kind === 'practice' && !position.hint && (
                <button type="button" disabled={blocked} onClick={() => act('hint')}>Взять подсказку</button>
              )}
              <button type="button" disabled={blocked} onClick={() => act('reveal')}>Показать решение</button>
            </div>
          </>
        ) : feedback && (
          <>
            <p role="status">
              {feedback.correct === null ? 'Решение показано без попытки.' : feedback.correct ? 'Ход засчитан.' : 'Ход не засчитан.'}
            </p>
            {feedback.original_text && <p>{feedback.text}</p>}
            {originalMove && <p>Ход в партии: {toFigurine(originalMove.san)}.</p>}
            <p>{feedback.original_text ?? feedback.text}</p>
            {moves.length > 0 && (
              <div className={css.controls}>
                <button type="button" disabled={lineStep === 0} onClick={() => setLineStep(lineStep - 1)}>Предыдущий ход решения</button>
                <button type="button" disabled={lineStep === moves.length} onClick={() => setLineStep(lineStep + 1)}>Следующий ход решения</button>
              </div>
            )}
            {current && <p role="status">{toFigurine(current.san)} · {lineStep} из {moves.length}</p>}
            <button type="button" disabled={blocked} onClick={() => act('next')}>
              {session.step === session.total ? 'К итогам' : 'Следующее упражнение'}
            </button>
          </>
        )}
        <div className={css.controls}>
          <button type="button" disabled={blocked} onClick={() => act('finish')}>Закончить занятие</button>
        </div>
      </div>
    </div>
  )
}
