import { useCallback, useRef, useState } from 'react'
import type { CoachResult } from '../api/client'
import { addPlayMistake } from '../api/mistakes'
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

/**
 * After a player move: holds the opponent reply (gate) until the coach has answered.
 * Which answers show advice depends on the help level (see coachSettings). Only a blunder
 * keeps the gate shut until `proceed`. `verdicts` keeps the class of each move by `${game id}:${ply}`.
 */
export function useCoach() {
  const [advice, setAdvice] = useState<Advice | null>(null)
  const [verdicts, setVerdicts] = useState<Record<string, string>>({})
  const gate = useRef<Gate | null>(null)

  const reset = useCallback(() => {
    gate.current = null
    setAdvice(null)
  }, [])

  const begin = useCallback((id: number, len: number, verdict: Promise<Verdict>, before: string, uci: string, after: string) => {
    let release!: () => void
    const me: Gate = { id, len, release: () => release(), promise: new Promise<void>((r) => (release = r)) }
    gate.current = me
    setAdvice(null)
    const key = `${id}:${len - 1}`
    setVerdicts((p) => Object.fromEntries(Object.entries(p).filter(([k]) => k !== key)))
    void verdict.then((v) => {
      if (gate.current !== me) return
      if (v) setVerdicts((p) => ({ ...p, [key]: v.facts.classification }))
      const bad = v?.facts.classification === 'mistake' || v?.facts.classification === 'blunder'
      const blunder = v?.facts.classification === 'blunder'
      const best = v?.facts.best_move
      if (v && bad && best) {
        const motif = v.facts.motifs_against?.[0]?.kind ?? v.facts.motifs_missed?.[0]?.kind
        addPlayMistake({ fen: before, best_uci: best.uci, played_uci: uci, classification: v.facts.classification, motif }).catch(() => {})
      }
      const level = readHelp()
      const cls = v?.facts.classification
      const shows = level >= 5 || (level >= 3 ? bad : level === 2 && cls === 'blunder')
      const text = v?.explanation?.text ?? (level >= 5 && cls ? CLASS_WORD[cls].replace(/^./, (c) => c.toUpperCase()) : '')
      if (v && shows && text) {
        setAdvice({ text, source: v.explanation?.source ?? '', lesson: v.facts.lesson, hold: blunder, facts: v.facts, before, uci, after })
        if (!blunder) release()
      } else release()
    })
  }, [])

  const wait = useCallback((id: number, len: number) => {
    const g = gate.current
    return g && g.id === id && g.len === len ? g.promise : Promise.resolve()
  }, [])

  const proceed = useCallback(() => {
    setAdvice(null)
    gate.current?.release()
  }, [])

  return { advice, verdicts, begin, wait, proceed, reset }
}
