import { useCallback, useEffect, useRef, useState } from 'react'
import { coachHint, type Hint } from '../api/client'
import type { Arrow } from './arrows'
import type { HelpLevel } from './coachSettings'
import { toFigurine } from './notation'

const PIECE: Record<string, string> = { P: 'пешка', N: 'конь', B: 'слон', R: 'ладья', Q: 'ферзь', K: 'король' }
/** The threat is the engine's strongest reply; the real opponent may play another move. */
const threatLine = (t: NonNullable<Hint['threat']>) => {
  const tail = t.mate ? ' и поставить мат' : t.wins ? ` и забрать ${t.wins}` : ''
  return `Угроза: если её не заметить, соперник может сыграть ${toFigurine(t.san)}${tail}.`
}
type State = { fen: string; step: number; hint: Hint | 'error' | null }

const arrow = (uci: string, color: Arrow['color']): Arrow => ({ from: uci.slice(0, 2), to: uci.slice(2, 4), color })

/**
 * The «Подсказка» button in a game: 1st press the opponent's threat, 2nd the piece to move,
 * 3rd the best move as an arrow. The steps start over in every position.
 * At level 5 the threat is asked for in every position and always drawn as a red arrow.
 * `canAsk` is true while it is the player's turn in a running game.
 */
export function useHelp(fen: string, level: HelpLevel, canAsk: boolean, onUsed: () => void) {
  const [st, setSt] = useState<State>({ fen, step: 0, hint: null })
  const cur = st.fen === fen ? st : { fen, step: 0, hint: null }
  const patch = useCallback(
    (p: Partial<State>) => setSt((s) => ({ ...(s.fen === fen ? s : { fen, step: 0, hint: null }), ...p })),
    [fen],
  )
  const current = useRef(fen) // the position now: a reply for an older one is dropped
  const asking = useRef<string | null>(null) // the position with a request on its way
  useEffect(() => {
    current.current = fen
  }, [fen])
  const load = useCallback(() => {
    if (asking.current === fen) return
    asking.current = fen
    const reply = (p: Partial<State>) => {
      if (asking.current === fen) asking.current = null
      if (current.current === fen) patch(p)
    }
    coachHint(fen).then(
      (hint) => reply({ hint }),
      () => reply({ hint: 'error' }),
    )
  }, [fen, patch])

  useEffect(() => {
    if (level >= 5 && canAsk) load()
  }, [level, canAsk, load])

  // A hint counts once in each position: a press or the automatic threat arrow at level 5.
  const counted = useRef<string | null>(null)
  const count = useCallback(() => {
    if (counted.current === fen) return
    counted.current = fen
    onUsed()
  }, [fen, onUsed])

  const hint = typeof cur.hint === 'object' ? cur.hint : null
  const autoThreat = level >= 5 && canAsk && !!hint?.threat
  useEffect(() => {
    if (autoThreat) count()
  }, [autoThreat, count])

  const press = () => {
    if (!canAsk) return
    if (cur.step === 0) {
      count()
      if (!cur.hint) load()
    }
    patch({ step: Math.min(cur.step + 1, 3) })
  }

  const arrows: Arrow[] = []
  const lines: string[] = []
  if (canAsk && hint?.threat && (level >= 5 || cur.step >= 1)) arrows.push(arrow(hint.threat.uci, 'red'))
  if (canAsk && hint && cur.step >= 3) arrows.push(arrow(hint.best.uci, 'green'))
  if (canAsk && cur.step >= 1) {
    if (cur.hint === 'error') lines.push('Подсказка сейчас недоступна.')
    else if (hint) {
      lines.push(hint.threat ? threatLine(hint.threat) : 'Явных угроз нет')
      if (cur.step >= 2) lines.push(`Ходите: ${PIECE[hint.best.piece] ?? 'любой фигурой'}`)
    }
  }
  return { press, arrows, lines }
}
