// Keeps the unfinished puzzle in localStorage (Safari may reload the tab).
import type { Puzzle } from '../api/client'
import { sessionKey } from '../auth/session'

const key = () => sessionKey('puzzle.current')
type Stored = { puzzle: Puzzle; theme: string; opening: string }

export function loadPuzzle(theme: string, opening: string): Puzzle | null {
  try {
    const s = JSON.parse(localStorage.getItem(key()) ?? 'null') as Partial<Stored> | null
    const p = s?.puzzle
    const ok =
      s?.theme === theme && s.opening === opening && p && typeof p.id === 'string' && typeof p.fen === 'string' &&
      typeof p.opponent_move === 'string' && Array.isArray(p.solution)
    return ok ? p : null
  } catch {
    return null
  }
}

export function storePuzzle(puzzle: Puzzle | null, theme = '', opening = '') {
  try {
    if (puzzle) localStorage.setItem(key(), JSON.stringify({ puzzle, theme, opening }))
    else localStorage.removeItem(key())
  } catch {
    /* the puzzle is not kept */
  }
}
