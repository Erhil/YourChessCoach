import { Chess } from 'chess.js'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { reviewGame, type KeyMoment, type ReviewResult } from '../api/review'
import { lineArrows, type Arrow } from '../chess/arrows'
import { splitUci } from '../chess/notation'
import { Board } from '../components/Board'
import { MoveList } from '../components/MoveList'
import { OpeningName } from '../components/OpeningName'
import { KeyMoments, MARKS } from './KeyMoments'
import { ReviewInput } from './ReviewInput'
import { markReviewRevealed, ReviewPractice } from './ReviewPractice'
import css from './Review.module.css'

const noMove = () => false
const NAV = [
  ['⏮', 'В начало'],
  ['◀', 'Назад'],
  ['▶', 'Вперёд'],
  ['⏭', 'В конец'],
] as const

export default function Review() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<ReviewResult | null>(null)
  const [asked, setAsked] = useState<Arrow[] | null>(null) // arrows of a coach answer
  const [cur, setCur] = useState(0) // number of plies shown
  const [shown, setShown] = useState<KeyMoment | null>(null)
  const [game, setGame] = useState<number | null>(null)
  const [practice, setPractice] = useState<KeyMoment | null>(null)
  const request = useRef<symbol | null>(null)

  // fens[k] is the position after k plies.
  const fens = useMemo(() => {
    if (!res) return []
    const last = res.moves[res.moves.length - 1]
    const board = new Chess(last.fen_before)
    board.move(splitUci(last.uci))
    return [...res.moves.map((m) => m.fen_before), board.fen()]
  }, [res])

  const uci = useMemo(() => res?.moves.map((m) => m.uci) ?? [], [res])

  const run = async (body: Parameters<typeof reviewGame>[0]) => {
    const id = Symbol()
    request.current = id
    setBusy(true)
    setError('')
    setRes(null)
    setShown(null)
    setAsked(null)
    setPractice(null)
    try {
      const r = await reviewGame(body)
      if (request.current !== id) return
      const saved = 'game_id' in body ? body.game_id : null
      window.history.replaceState(window.history.state, '', saved ? `?game=${saved}` : window.location.pathname)
      setGame(saved)
      setRes(r)
      setCur(r.moves.length)
    } catch (e) {
      if (request.current === id) {
        setError(String(e).includes('PGN') ? 'Не удалось прочитать PGN' : 'Не удалось сделать разбор')
      }
    } finally {
      if (request.current === id) setBusy(false)
    }
  }

  useLayoutEffect(() => () => { request.current = null }, [])

  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get('game'))
    // eslint-disable-next-line react-hooks/set-state-in-effect -- run sets state only after the request starts
    if (id > 0) void run({ game_id: id, practice: true })
  }, [])

  const go = (n: number) => {
    setShown(null)
    setAsked(null)
    setCur(n)
  }
  const target = [0, cur - 1, cur + 1, fens.length - 1]
  const arrows =
    asked ??
    (shown
    ? [
        ...lineArrows(shown.facts.fen_before, [shown.facts.player_move.uci]).map((a) => ({ ...a, color: 'red' as const })),
        ...lineArrows(shown.facts.fen_before, shown.facts.best_line.slice(0, 2)),
      ]
    : [])
  const lastUci = !shown && cur > 0 && res ? res.moves[cur - 1].uci : null

  return (
    <>
      <h1>Разбор партии</h1>
      <ReviewInput busy={busy} onGame={(game_id) => run({ game_id, practice: true })} onPgn={(pgn, side) => run({ pgn, side })} />
      {busy && <p role="status">Идёт разбор…</p>}
      {error && <p role="alert">{error}</p>}
      {res && game && practice && (
        <ReviewPractice key={`${game}:${practice.ply}`} game={game} moment={practice} side={res.side} onExit={() => setPractice(null)} />
      )}
      {res && !practice && (
        <div className={css.layout}>
          <div>
            <Board
              position={shown ? shown.facts.fen_before : fens[cur]}
              orientation={res.side}
              canMove={false}
              onMove={noMove}
              lastMove={lastUci ? splitUci(lastUci) : null}
              arrows={arrows}
            />
            <div className={css.nav}>
              {NAV.map(([glyph, label], i) => (
                <button
                  key={label}
                  type="button"
                  aria-label={label}
                  disabled={target[i] < 0 || target[i] >= fens.length}
                  onClick={() => go(target[i])}
                >
                  {glyph}
                </button>
              ))}
            </div>
          </div>
          <div className={css.side}>
            <p>
              Неточности: {res.summary.inaccuracy} · Ошибки: {res.summary.mistake} · Зевки: {res.summary.blunder}
            </p>
            <OpeningName moves={uci} />
            <MoveList
              moves={res.moves.map((m) => m.san)}
              marks={res.moves.map((m) => (m.color === res.side ? (MARKS[m.classification] ?? '') : ''))}
              current={shown ? -1 : cur - 1}
              onSelect={(ply) => go(ply + 1)}
            />
            <h2>Ключевые моменты</h2>
            <KeyMoments
              moments={res.key_moments}
              shown={shown}
              onShow={(m) => {
                if (game) markReviewRevealed(game, m.ply)
                setAsked(null)
                setShown(m)
              }}
              onAsk={(m, a) => {
                setShown(m)
                setAsked(a)
              }}
              onPractice={game ? (m) => {
                setShown(null)
                setAsked(null)
                setPractice(m)
              } : undefined}
            />
          </div>
        </div>
      )}
    </>
  )
}
