import { sessionKey } from '../auth/session'
// Keeps the running game and the last setup choice in localStorage (Safari may reload the tab).
export type StoredGame = { id: number; color: 'white' | 'black'; level: number; sans: string[]; hints?: number; takebacks?: number }
export type Prefs = { color: 'white' | 'black' | 'random'; level: number }

const PREFS_KEY = 'play.prefs'

function read(key: string): unknown {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* the game is not kept */
  }
}

export function loadGame(): StoredGame | null {
  const g = read(sessionKey('play.game')) as Partial<StoredGame> | null
  const ok =
    g && typeof g.id === 'number' && typeof g.level === 'number' && (g.color === 'white' || g.color === 'black') &&
    Array.isArray(g.sans) && g.sans.every((s) => typeof s === 'string')
  return ok ? (g as StoredGame) : null
}
export const storeGame = (g: StoredGame | null) => write(sessionKey('play.game'), g)

export function loadPrefs(): Prefs {
  const p = read(PREFS_KEY) as Partial<Prefs> | null
  const color = p?.color === 'black' || p?.color === 'random' ? p.color : 'white'
  return { color, level: typeof p?.level === 'number' ? p.level : 800 }
}
export const storePrefs = (p: Prefs) => write(PREFS_KEY, p)
