import { sendAttempt, type AttemptDetails, type AttemptResult } from '../api/client'
import { sessionLogin } from '../auth/session'

export interface PendingAttempt {
  client_id: string
  login: string
  puzzle: string
  solved: boolean
  used_hint: boolean
  details?: AttemptDetails
}
const memory = new Map<string, PendingAttempt[]>()
const active = new Map<string, { entry: PendingAttempt; request: Promise<AttemptResult> }>()
const failures = new Set<string>()
const unavailable = new Set<string>()
export const RESULT_QUEUE_EVENT = 'puzzle-results-changed'
const key = (login: string) => `chess-puzzle-results:${login}`
const notify = () => window.dispatchEvent(new Event(RESULT_QUEUE_EVENT))

export function pendingAttempts(login = sessionLogin()): PendingAttempt[] {
  if (unavailable.has(login)) return memory.get(login) ?? []
  try {
    const raw = localStorage.getItem(key(login))
    const entries: PendingAttempt[] = raw ? JSON.parse(raw) : []
    if (!Array.isArray(entries) || entries.some((e) => e.login !== login || typeof e.client_id !== 'string' || typeof e.puzzle !== 'string' || typeof e.solved !== 'boolean' || typeof e.used_hint !== 'boolean')) throw new Error('Invalid queue')
    memory.set(login, entries)
  } catch {
    unavailable.add(login)
  }
  return memory.get(login) ?? []
}

function write(login: string, entries: PendingAttempt[]) {
  memory.set(login, entries)
  try {
    localStorage.setItem(key(login), JSON.stringify(entries))
  } catch {
    unavailable.add(login)
  }
  notify()
}

export function newAttemptId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function enqueueAttempt(puzzle: string, solved: boolean, used_hint: boolean, client_id = newAttemptId(), details?: AttemptDetails) {
  const login = sessionLogin()
  const entries = pendingAttempts(login)
  const existing = entries.find((e) => e.client_id === client_id)
  if (existing && (!details?.revealed || !existing.details || existing.details.revealed)) return existing
  const entry = existing
    ? { ...existing, details: { ...existing.details!, revealed: true } }
    : { login, client_id, puzzle, solved, used_hint, details }
  write(login, existing ? entries.map((e) => e === existing ? entry : e) : [...entries, entry])
  return entry
}

export function deliverAttempt(entry: PendingAttempt): Promise<AttemptResult> {
  const id = `${entry.login}:${entry.client_id}`
  if (sessionLogin() !== entry.login) return Promise.reject(new Error('Session changed'))
  const running = active.get(id)
  if (running) {
    if (entry.details?.revealed && !running.entry.details?.revealed) {
      return running.request.catch(() => {}).then(() => deliverAttempt(entry))
    }
    return running.request
  }
  const request = sendAttempt(entry.puzzle, entry.solved, entry.used_hint, entry.client_id, entry.details, entry.login).then((result) => {
    // Read the latest queue: a delayed response must preserve later results.
    write(entry.login, pendingAttempts(entry.login).filter((e) =>
      e.client_id !== entry.client_id || (e.details?.revealed && !entry.details?.revealed)))
    failures.delete(id)
    return result
  }).catch((error: unknown) => {
    failures.add(id)
    throw error
  }).finally(() => {
    active.delete(id)
    notify()
  })
  active.set(id, { entry, request })
  return request
}

export async function retryAttempts() {
  const login = sessionLogin()
  for (const entry of pendingAttempts(login)) {
    if (sessionLogin() !== login) break
    try { await deliverAttempt(entry) } catch { break }
  }
}

export function queueStatus(login: string) {
  const count = pendingAttempts(login).length
  return { count, warning: unavailable.has(login), failed: [...failures].some((id) => id.startsWith(`${login}:`)) }
}
