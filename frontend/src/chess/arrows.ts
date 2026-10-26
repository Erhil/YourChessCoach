import { Chess } from 'chess.js'
import { splitUci } from './notation'

export type Arrow = { from: string; to: string; color: 'green' | 'red'; step?: number }

const UCI = /^[a-h][1-8][a-h][1-8][qrbn]?$/

/**
 * Turns a line (SAN or UCI moves from `fen`) into at most 3 arrows.
 * Moves of the side to move are green, the replies are red; `step` grows along the line.
 * Stops at the first illegal move.
 */
export function lineArrows(fen: string, moves: string[]): Arrow[] {
  const chess = new Chess(fen)
  const out: Arrow[] = []
  for (const [step, m] of moves.slice(0, 3).entries()) {
    try {
      const made = UCI.test(m) ? chess.move(splitUci(m)) : chess.move(m)
      out.push({ from: made.from, to: made.to, color: step % 2 === 0 ? 'green' : 'red', step })
    } catch {
      break
    }
  }
  return out
}

/** For «Показать на доске»: the opponent's reply (red, from the position after `uci`) and the better move (green).
 * Only the first move of the refutation: the next one is the player's own, and a red arrow would read as a threat. */
export function adviceArrows(
  before: string,
  uci: string,
  f: { best_line?: string[]; best_move?: { uci: string } | null; refutation?: string[] },
): Arrow[] {
  const best = f.best_line?.[0] ?? f.best_move?.uci
  let reply: Arrow[] = []
  try {
    const chess = new Chess(before)
    chess.move(splitUci(uci))
    reply = lineArrows(chess.fen(), f.refutation ?? []).slice(0, 1).map((a) => ({ ...a, color: 'red' }))
  } catch {
    /* no reply to draw */
  }
  return [...reply, ...(best ? lineArrows(before, [best]) : [])]
}
