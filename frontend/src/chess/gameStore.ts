import type { GameRecord } from '../api/client'
import { sessionKey } from '../auth/session'
// Keeps the running game and the last setup choice in localStorage (Safari may reload the tab).
export type StoredGame = { clientId?: string; id: number; color: 'white' | 'black'; level: number; sans: string[]; hints?: number; takebacks?: number }
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

// Capture the key at mount. A late response cannot write into another login's queue.
export const pendingKey = () => sessionKey('play.pending')
// Each save owns one key. Completing one request cannot overwrite another tab's save.
export function loadPending(key: string): GameRecord[] {
  // Upgrade the whole-queue format without dropping records if a write fails.
  const legacy = read(key) as GameRecord[] | null
  if (Array.isArray(legacy)) {
    for (const game of legacy) {
      const name = `${key}:${game.client_id}`
      if (localStorage.getItem(name) === null) localStorage.setItem(name, JSON.stringify(game))
    }
    localStorage.removeItem(key)
  }
  const games: GameRecord[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const name = localStorage.key(i)
    if (name?.startsWith(`${key}:`)) {
      const game = read(name) as GameRecord | null
      if (game) games.push(game)
    }
  }
  return games
}
export function storePending(key: string, game: GameRecord) {
  localStorage.setItem(`${key}:${game.client_id}`, JSON.stringify(game))
  window.dispatchEvent(new Event('pending-games'))
}
export function removePending(key: string, id: string) {
  localStorage.removeItem(`${key}:${id}`)
  window.dispatchEvent(new Event('pending-games'))
}
