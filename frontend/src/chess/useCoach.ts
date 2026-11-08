import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { CoachResult, GameError } from '../api/client'
import { readHelp } from './coachSettings'
import { CLASS_WORD } from './notation'

export type Verdict = CoachResult | null
/** `hold`: the opponent reply waits for «Играть дальше». Only a blunder holds; other notes do not. */
export type Advice = {
  text: string
  source: string
  lesson: CoachResult['facts']['lesson']
  hold: boolean
  facts: CoachResult['facts']
  before: string
  uci: string
  /** The position after the player move: the arrows of this note fit only this position. */
  after: string
}
type Gate = { id: number; len: number; promise: Promise<void>; release: () => void }
type MoveCheck = { task?: Promise<void>; verdict?: Verdict }

// A route change does not cancel a confirmed move's engine request.
const checks = new Map<string, Map<number, MoveCheck>>()
const empty: Record<string, string> = {}
const verdictsByGame = new Map<string, Record<string, string>>()
const viewing = new Set<string>()
const changes = new EventTarget()
const subscribe = (callback: () => void) => {
  changes.addEventListener('change', callback)
  return () => changes.removeEventListener('change', callback)
}

function publish(clientId: string, id: number) {
  const verdicts: Record<string, string> = {}
  for (const [ply, check] of checks.get(clientId) ?? []) {
    if (check.verdict) verdicts[`${id}:${ply}`] = check.verdict.facts.classification
  }
  verdictsByGame.set(clientId, verdicts)
  changes.dispatchEvent(new Event('change'))
}

export function gameAnalysis(clientId: string) {
  const errors: GameError[] = []
  for (const [ply, check] of checks.get(clientId) ?? []) {
    const facts = check.verdict?.facts
    if (facts?.best_move && (facts.classification === 'mistake' || facts.classification === 'blunder')) {
      errors.push({
        ply: ply + 1, best_uci: facts.best_move.uci, best_line: facts.best_line, classification: facts.classification,
        motif: facts.motifs_against?.[0]?.kind ?? facts.motifs_missed?.[0]?.kind,
      })
    }
  }
  return { verdicts: verdictsByGame.get(clientId) ?? empty, errors }
}

export async function finishCoach(clientId: string) {
  await Promise.all([...checks.get(clientId)?.values() ?? []].map((check) => check.task))
  const analysis = gameAnalysis(clientId)
  checks.delete(clientId)
  if (!viewing.has(clientId)) verdictsByGame.delete(clientId)
  return analysis
}

/**
 * After a player move: holds the opponent reply (gate) until the coach has answered.
 * Which answers show advice depends on the help level (see coachSettings). Only a blunder
 * keeps the gate shut until `proceed`. `verdicts` keeps the class of each move by `${game id}:${ply}`.
 */
export function useCoach(clientId: string | undefined) {
  const [advice, setAdvice] = useState<Advice | null>(null)
  const verdicts = useSyncExternalStore(subscribe, () => verdictsByGame.get(clientId ?? '') ?? empty)
  const gate = useRef<Gate | null>(null)

  useEffect(() => {
    if (!clientId) return
    viewing.add(clientId)
    return () => {
      viewing.delete(clientId)
      if (!checks.has(clientId)) verdictsByGame.delete(clientId)
    }
  }, [clientId])

  const reset = useCallback(() => {
    gate.current?.release()
    gate.current = null
    setAdvice(null)
  }, [])

  useEffect(() => () => {
    gate.current?.release()
    gate.current = null
  }, [])

  const begin = (clientId: string, id: number, len: number, verdict: Promise<Verdict>, before: string, uci: string, after: string) => {
    let release!: () => void
    const me: Gate = { id, len, release: () => release(), promise: new Promise<void>((r) => (release = r)) }
    gate.current = me
    setAdvice(null)
    const ply = len - 1
    const game = checks.get(clientId) ?? new Map<number, MoveCheck>()
    checks.set(clientId, game)
    const check: MoveCheck = {}
    game.set(ply, check)
    check.task = verdict.then((v) => {
      if (game.get(ply) !== check) return
      check.verdict = v
      publish(clientId, id)
      const bad = v?.facts.classification === 'mistake' || v?.facts.classification === 'blunder'
      const blunder = v?.facts.classification === 'blunder'
      if (gate.current !== me) return
      const level = readHelp()
      const cls = v?.facts.classification
      const shows = level >= 5 || (level >= 3 ? bad : level === 2 && cls === 'blunder')
      const text = v?.explanation?.text ?? (level >= 5 && cls ? CLASS_WORD[cls].replace(/^./, (c) => c.toUpperCase()) : '')
      if (v && shows && text) {
        setAdvice({ text, source: v.explanation?.source ?? '', lesson: v.facts.lesson, hold: blunder, facts: v.facts, before, uci, after })
        if (!blunder) release()
      } else release()
    }).finally(() => { delete check.task })
    if (readHelp() === 1) release()
  }

  const discard = (clientId: string, id: number, from: number) => {
    const game = checks.get(clientId)
    if (!game) return
    for (const ply of game.keys()) {
      if (ply >= from) game.delete(ply)
    }
    publish(clientId, id)
  }

  const wait = useCallback((id: number, len: number) => {
    const g = gate.current
    return g && g.id === id && g.len === len ? g.promise : Promise.resolve()
  }, [])

  const proceed = useCallback(() => {
    setAdvice(null)
    gate.current?.release()
  }, [])

  return { advice, verdicts, begin, wait, proceed, reset, discard }
}
