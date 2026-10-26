import { Chess } from 'chess.js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { coachMove, getOpponentMove, saveGame } from '../api/client'
import type { Move } from '../components/Board'
import { sleep, toUci } from './notation'
import { readHelp } from './coachSettings'
import { gameStatus, type GameStatus } from './game'
import { loadGame, storeGame } from './gameStore'
import { useCoach, type Verdict } from './useCoach'

type Color = 'white' | 'black'
export type Game = { id: number; color: Color; level: number; sans: string[]; hints?: number; takebacks?: number }

const ask = (fen: string, uci: string): Promise<Verdict> => coachMove(fen, uci).catch(() => null)

function replay(sans: string[]): Chess {
  const chess = new Chess()
  for (const san of sans) chess.move(san)
  return chess
}

/** The game kept from the last visit; a broken or finished one is dropped. */
function restore(): Game | null {
  const stored = loadGame()
  if (!stored) return null
  try {
    return gameStatus(replay(stored.sans)).over ? null : stored
  } catch {
    return null
  }
}

function pgnOf(g: Game, result: string): string {
  const chess = replay(g.sans)
  const me = 'Вы'
  const bot = `Соперник ${g.level}`
  chess.setHeader('White', g.color === 'white' ? me : bot)
  chess.setHeader('Black', g.color === 'white' ? bot : me)
  chess.setHeader('Result', result)
  return chess.pgn()
}

/** The ply (index in `sans`) is a move of the player. */
const isPlayerPly = (g: Game, ply: number) => ply >= 0 && ply % 2 === (g.color === 'white' ? 0 : 1)

/**
 * Player moves that the coach classified as a blunder. The count is known only when every player move has a verdict:
 * a missing verdict (failed request, restored game, game saved before the last verdict) gives undefined,
 * which the server keeps as NULL. A final player move that gives checkmate is never a blunder and needs no verdict.
 */
export function countBlunders(g: Game, verdicts: Record<string, string>, termination: string): number | undefined {
  const mate = termination === 'checkmate' && isPlayerPly(g, g.sans.length - 1) ? g.sans.length - 1 : -1
  const plies = g.sans.map((_, ply) => ply).filter((ply) => isPlayerPly(g, ply) && ply !== mate)
  return plies.every((ply) => `${g.id}:${ply}` in verdicts)
    ? plies.filter((ply) => verdicts[`${g.id}:${ply}`] === 'blunder').length
    : undefined
}

/** Own moves made by the player (for black the opponent's first move does not count). */
const ownMoves = (g: Game) => (g.color === 'white' ? Math.ceil(g.sans.length / 2) : Math.floor(g.sans.length / 2))

export function useGame() {
  const [g, setG] = useState<Game | null>(restore)
  const [resigned, setResigned] = useState(false)
  const [savedGameId, setSavedGameId] = useState<number | null>(null)
  const [oppError, setOppError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState(false)
  const nextId = useRef((g?.id ?? 0) + 1)
  const savedId = useRef(0)
  const coach = useCoach()
  const { wait: coachWait } = coach
  const epoch = useRef(0) // grows on a new game and on undo: drops a pending coach check
  const [checking, setChecking] = useState(false)
  const [warn, setWarn] = useState<{ m: Move; v: Verdict } | null>(null)

  const sans = useMemo(() => g?.sans ?? [], [g])
  const chess = useMemo(() => replay(sans), [sans])
  const status = useMemo<GameStatus>(
    () =>
      resigned && g
        ? { over: true, result: g.color === 'white' ? '0-1' : '1-0', termination: 'resign' }
        : gameStatus(chess),
    [chess, resigned, g],
  )
  const uci = useMemo(() => chess.history({ verbose: true }).map(toUci), [chess])
  const fen = chess.fen()
  const last = chess.history({ verbose: true }).at(-1)
  const playerTurn = chess.turn() === (g?.color === 'black' ? 'b' : 'w')
  const active = !!g && !status.over
  const oppKey = g ? `${g.id}:${sans.length}` : ''
  const thinking = active && !playerTurn && oppError !== oppKey

  const { verdicts } = coach
  const save = useCallback((game: Game, result: string, termination: string, remember = false) => {
    const blunders = countBlunders(game, verdicts, termination)
    // The server accepts at most 600 of each.
    const takebacks = Math.min(game.takebacks ?? 0, 600)
    const hints = Math.min(game.hints ?? 0, 600)
    saveGame({ pgn: pgnOf(game, result), player_color: game.color, level: game.level, result, termination, blunders, takebacks, hints }).then(
      (r) => remember && setSavedGameId(r.id),
      () => setSaveError(true),
    )
  }, [verdicts])

  // Keep the running game for the next visit.
  useEffect(() => {
    storeGame(g && !status.over ? g : null)
  }, [g, status.over])

  // Opponent reply. The cleanup drops a reply that comes after the position changed.
  useEffect(() => {
    if (!g || !thinking) return
    let stale = false
    const { id, level } = g
    const len = sans.length
    Promise.all([getOpponentMove(uci, level), sleep(300), coachWait(id, len)])
      .then(([m]) => {
        if (!stale) setG((p) => (p && p.id === id && p.sans.length === len ? { ...p, sans: [...p.sans, m.san] } : p))
      })
      .catch(() => {
        if (!stale) setOppError(`${id}:${len}`)
      })
    return () => {
      stale = true
    }
  }, [g, thinking, uci, sans.length, coachWait])

  // Save a finished game once.
  useEffect(() => {
    if (g && status.over && savedId.current !== g.id) {
      savedId.current = g.id
      save(g, status.result, status.termination, true)
    }
  }, [g, status, save])

  const dropCoach = () => {
    epoch.current++
    coach.reset()
    setChecking(false)
    setWarn(null)
  }

  const start = (colorChoice: Color | 'random', level: number) => {
    const color = colorChoice === 'random' ? (Math.random() < 0.5 ? 'white' : 'black') : colorChoice
    setSaveError(false)
    setOppError(null)
    setResigned(false)
    setSavedGameId(null)
    dropCoach()
    setG({ id: nextId.current++, color, level, sans: [] })
  }

  /** Back to the setup card. A running game with moves is saved as unfinished. */
  const leave = () => {
    if (g && !status.over && ownMoves(g) > 0) save(g, '*', 'abandoned')
    setResigned(false)
    setSavedGameId(null)
    setOppError(null)
    dropCoach()
    setG(null)
  }
  const resign = () => {
    if (!active) return
    dropCoach()
    setResigned(true)
  }

  const canMove = active && playerTurn && !checking && !warn
  // Plays the move. `v` is a coach answer already received; undefined means: ask the coach now.
  const apply = (m: Move, v?: Verdict): boolean => {
    if (!g) return false
    try {
      const c = replay(sans)
      const before = c.fen()
      const played = c.move({ from: m.from, to: m.to, promotion: m.promotion })
      const mv = toUci(m)
      // The verdict is asked for every move: notes, icons and the mistakes deck all use it.
      coach.begin(g.id, sans.length + 1, v === undefined ? ask(before, mv) : Promise.resolve(v), before, mv, c.fen())
      setG({ ...g, sans: [...sans, played.san] })
      return true
    } catch {
      return false
    }
  }

  const move = (m: Move): boolean => {
    if (!g || !canMove) return false
    if (readHelp() < 4) return apply(m)
    try {
      const c = replay(sans)
      const before = c.fen()
      c.move({ from: m.from, to: m.to, promotion: m.promotion })
      const ep = epoch.current
      setChecking(true)
      void ask(before, toUci(m)).then((v) => {
        if (epoch.current !== ep) return
        setChecking(false)
        if (v?.facts.classification === 'blunder') setWarn({ m, v })
        else apply(m, v)
      })
    } catch {
      /* illegal move */
    }
    return false
  }
  /** «Подумать ещё» cancels the move as a takeback does, so it counts as one. */
  const warnThink = () => {
    if (!warn) return
    setWarn(null)
    setG((p) => p && { ...p, takebacks: (p.takebacks ?? 0) + 1 })
  }
  const warnGo = () => {
    if (!warn) return
    setWarn(null)
    apply(warn.m, warn.v)
  }

  /** A hint was used: the game counts it. */
  const markHint = useCallback(() => setG((p) => p && { ...p, hints: (p.hints ?? 0) + 1 }), [])

  const canUndo = !!g && active && ownMoves(g) > 0
  const undo = () => {
    if (!g || !canUndo) return
    setOppError(null)
    dropCoach()
    setG({ ...g, sans: sans.slice(0, sans.length - (playerTurn ? 2 : 1)), takebacks: (g.takebacks ?? 0) + 1 })
  }

  return {
    g, fen, sans, uci, status, active, thinking, canMove, canUndo, oppFailed: active && !playerTurn && !thinking,
    saveError, savedGameId, checking, warn, warnThink, warnGo, advice: coach.advice, verdicts: coach.verdicts, proceed: coach.proceed,
    lastMove: last ? { from: last.from, to: last.to } : null, start, leave, resign, move, undo, markHint,
  }
}
