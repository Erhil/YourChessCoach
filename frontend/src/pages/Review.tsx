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

type ReviewView = {
  side: ReviewResult['side']
  shown: KeyMoment | null
  asked: { arrows: Arrow[]; fen: string } | null
}

export default function Review() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState<ReviewResult | null>(null)
  const [view, setView] = useState<ReviewView>({ side: 'white', shown: null, asked: null })
  const [cur, setCur] = useState(0) // number of plies shown
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
    setView({ side: 'white', shown: null, asked: null })
    setPractice(null)
    try {
      const r = await reviewGame({ ...body, both_sides: true })
      if (request.current !== id) return
      const saved = 'game_id' in body ? body.game_id : null
      window.history.replaceState(window.history.state, '', saved ? `?game=${saved}` : window.location.pathname)
      setGame(saved)
      setRes(r)
      setView({ side: r.side, shown: null, asked: null })
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

  const { side, shown, asked } = view
  const clearView = (nextSide = side) => setView({ side: nextSide, shown: null, asked: null })
  const go = (n: number) => {
    clearView()
    setCur(n)
  }
  const sideReview = side === res?.side ? res : res?.other_side
  const color = side === 'white' ? 'Белые' : 'Чёрные'
  const opposite = side === 'white' ? 'black' : 'white'
  const flip = () => {
    if (shown) {
      // Keep the reply position when it follows the played move. A variant returns to its starting moment.
      const afterPlayedMove = asked?.arrows.length && asked.fen === fens[shown.ply]
      setCur(afterPlayedMove ? shown.ply : shown.ply - 1)
    }
    clearView(opposite)
  }
  const target = [0, cur - 1, cur + 1, fens.length - 1]
  const arrows =
    asked?.arrows ??
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
        <ReviewPractice key={`${game}:${practice.ply}`} game={game} moment={practice} side={side} onExit={() => setPractice(null)} />
      )}
      {res && sideReview && !practice && (
        <div className={css.layout}>
          <div>
            <Board
              position={asked?.arrows.length ? asked.fen : shown?.facts.fen_before ?? fens[cur]}
              orientation={side}
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
            {res.other_side && (
              <button className={css.flip} type="button" onClick={flip}>Перевернуть доску</button>
            )}
          </div>
          <div className={css.side}>
            <p>
              {color}. Неточности: {sideReview.summary.inaccuracy} · Ошибки: {sideReview.summary.mistake} · Зевки: {sideReview.summary.blunder}
            </p>
            <OpeningName moves={uci} />
            <MoveList
              moves={res.moves.map((m) => m.san)}
              start={{ fullmove: Number(fens[0].split(' ')[5]), black: res.moves[0].color === 'black' }}
              marks={res.moves.map((m) => (res.other_side || m.color === side ? (MARKS[m.classification] ?? '') : ''))}
              current={shown ? -1 : cur - 1}
              onSelect={(ply) => go(ply + 1)}
            />
            <h2>Ключевые моменты</h2>
            <KeyMoments
              moments={sideReview.key_moments}
              side={side}
              shown={shown}
              onShow={(m) => {
                if (game) markReviewRevealed(game, m.ply)
                setView({ side, shown: m, asked: null })
              }}
              onAsk={(m, arrows, fen) => {
                // A delayed coach answer must not move the board after navigation or a flip.
                setView((current) => current === view ? { side, shown: m, asked: { arrows, fen } } : current)
              }}
              onPractice={game ? (m) => {
                clearView()
                setPractice(m)
              } : undefined}
            />
          </div>
        </div>
      )}
    </>
  )
}
