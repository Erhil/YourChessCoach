import { Chess, type Square } from 'chess.js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  coachMove,
  getNextPuzzle,
  getPuzzleRating,
  getPuzzleThemes,
  type AttemptDetails,
  type AttemptResult,
  type Puzzle,
  type PuzzleTheme,
} from '../api/client'
import { getPuzzleOpenings, type PuzzleOpening } from '../api/openings'
import { sessionLogin } from '../auth/session'
import { lineArrows } from '../chess/arrows'
import { splitUci, sleep, toUci } from '../chess/notation'
import { enqueueAttempt, deliverAttempt, newAttemptId, type PendingAttempt } from './resultQueue'
import { loadPuzzle, storePuzzle } from './puzzleStore'
import type { Move } from '../components/Board'

export type Phase = 'loading' | 'opp' | 'play' | 'solved' | 'failed' | 'solution' | 'error'

const PIECES = { k: 'король', q: 'ферзь', r: 'ладья', b: 'слон', n: 'конь', p: 'пешка' }
const NO_EXPLANATION = 'Этот ход не решает задачу.'
const BLUE = 'rgb(20 120 220 / 45%)'

const apply = (chess: Chess, uci: string) => chess.move(splitUci(uci))

export function usePuzzle() {
  const [login] = useState(sessionLogin)
  const [themes, setThemes] = useState<PuzzleTheme[]>([])
  const [initialTheme] = useState(() => new URLSearchParams(window.location.search).get('theme') ?? '')
  const [theme, setTheme] = useState(initialTheme)
  const [openings, setOpenings] = useState<PuzzleOpening[]>([])
  const [initialOpening] = useState(() => new URLSearchParams(window.location.search).get('opening') ?? '')
  const [opening, setOpening] = useState(initialOpening)
  const [rating, setRating] = useState<number | null>(null)
  const [p, setP] = useState<Puzzle | null>(null)
  const [played, setPlayed] = useState<string[]>([]) // opponent_move, then solution moves
  const [wrong, setWrong] = useState<string | null>(null)
  const [phase, setPhase] = useState<Phase>('loading')
  const [hints, setHints] = useState(0)
  const [result, setResult] = useState<AttemptResult | null>(null)
  const [coach, setCoach] = useState<{ text: string; source?: string } | undefined>()
  const run = useRef(0) // a newer run cancels the older timers
  const hintsRef = useRef(0)
  const attemptId = useRef(newAttemptId())
  const started = useRef(0)
  const finished = useRef<PendingAttempt | null>(null)

  const base = useMemo(() => {
    const chess = new Chess(p?.fen)
    for (const uci of played) apply(chess, uci)
    return chess
  }, [p, played])
  const fen = useMemo(() => {
    if (!wrong) return base.fen()
    const chess = new Chess(base.fen())
    apply(chess, wrong)
    return chess.fen()
  }, [base, wrong])
  const lastUci = wrong ?? played.at(-1)
  const lastMove = lastUci ? splitUci(lastUci) : null
  const k = played.length - 1 // index of the next solution move
  const next = phase === 'play' ? p?.solution[k] : undefined

  const finish = async (id: string, solved: boolean, ply: number, uci: string | null, revealed = false) => {
    if (sessionLogin() !== login) return
    const token = run.current
    const prior = finished.current
    const details: AttemptDetails = prior?.details
      ? { ...prior.details, revealed }
      : { ply, played_uci: uci, first_uci: hintsRef.current === 0 ? uci : null, revealed, elapsed_ms: Math.round(performance.now() - started.current) }
    const entry = enqueueAttempt(id, solved, prior?.used_hint ?? (revealed || hintsRef.current > 0), attemptId.current, details)
    finished.current = entry
    storePuzzle(null)
    try {
      const r = await deliverAttempt(entry)
      if (run.current !== token || sessionLogin() !== login) return
      setResult(r)
      setRating(Math.round(r.rating_after))
    } catch {
      /* The global result queue shows the failure and offers retry. */
    }
  }

  const load = useCallback(async (th: string, op: string, keep = false) => {
    const t = ++run.current
    try {
      const exclude = new URLSearchParams(window.location.search).get('exclude') ?? ''
      const stored = keep ? loadPuzzle(th, op) : null
      const pz = (stored && stored.id !== exclude ? stored : null) || (await getNextPuzzle(th, op, exclude))
      if (run.current !== t) return
      attemptId.current = newAttemptId()
      finished.current = null
      storePuzzle(pz, th, op)
      setP(pz)
      setPhase('opp')
      await sleep(600)
      if (run.current !== t) return
      setPlayed([pz.opponent_move])
      started.current = performance.now()
      setPhase('play')
    } catch {
      if (run.current === t) setPhase('error')
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load sets state only after the fetch resolves
    void load(initialTheme, initialOpening, true)
    getPuzzleThemes().then(setThemes, () => {})
    getPuzzleOpenings().then(setOpenings, () => {})
    const ratingRun = run.current
    getPuzzleRating().then((r) => { if (run.current === ratingRun) setRating(Math.round(r.overall)) }, () => {})
    const token = run
    return () => {
      token.current++
    }
  }, [load, initialTheme, initialOpening])

  const again = () => {
    setPhase('loading')
    setPlayed([])
    setWrong(null)
    setResult(null)
    setCoach(undefined)
    setHints(0)
    hintsRef.current = 0
    void load(theme, opening)
  }

  const move = (m: Move): boolean => {
    if (phase !== 'play' || !p) return false
    const chess = new Chess(base.fen())
    let made
    try {
      made = chess.move(m)
    } catch {
      return false
    }
    const uci = toUci(made)
    const ply = k / 2 + 1
    const sol = p.solution
    const mate = chess.isCheckmate()
    if (uci !== sol[k] && !(k >= sol.length - 2 && mate)) {
      setWrong(uci)
      setPhase('failed')
      void finish(p.id, false, ply, uci)
      const token = run.current
      coachMove(base.fen(), uci).then(
        (r) => { if (run.current === token) setCoach(r.explanation ?? { text: NO_EXPLANATION }) },
        () => { if (run.current === token) setCoach({ text: NO_EXPLANATION }) },
      )
      return true
    }
    const t = ++run.current
    const reply = sol[k + 1]
    setPlayed([...played, uci])
    if (mate || !reply) {
      setPhase('solved')
      void finish(p.id, true, ply, uci)
      return true
    }
    setPhase('opp')
    void sleep(400).then(() => {
      if (run.current !== t) return
      setPlayed((pl) => [...pl, reply])
      if (k + 2 >= sol.length) {
        setPhase('solved')
        void finish(p.id, true, ply, uci)
      } else setPhase('play')
    })
    return true
  }

  const hint = () => {
    hintsRef.current = Math.min(2, hintsRef.current + 1)
    setHints(hintsRef.current)
  }

  const showSolution = async () => {
    if (!p || (phase !== 'play' && phase !== 'failed')) return
    const t = ++run.current
    setWrong(null)
    setPhase('solution')
    void finish(p.id, false, k / 2 + 1, null, true)
    for (const uci of p.solution.slice(k)) {
      await sleep(700)
      if (run.current !== t) return
      setPlayed((pl) => [...pl, uci])
    }
  }

  let hintText = ''
  const highlights: Record<string, string> = {}
  if (next && hints > 0) {
    const piece = base.get(next.slice(0, 2) as Square)
    hintText = `Ходит ${piece ? PIECES[piece.type] : 'фигура'}`
    highlights[next.slice(0, 2)] = BLUE
  }
  const arrows =
    next && hints > 1
      ? lineArrows(base.fen(), [next])
      : phase === 'solution' && p
        ? lineArrows(base.fen(), p.solution.slice(k))
        : []

  return {
    themes, theme, setTheme, openings, opening, setOpening, rating, p, phase, fen, lastMove, result, coach, hint, hints, hintText,
    highlights, arrows, move, showSolution, next: again,
  }
}
