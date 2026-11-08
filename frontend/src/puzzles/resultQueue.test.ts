import { beforeEach, expect, test, vi } from 'vitest'
import { setSessionLogin } from '../auth/session'
import { deliverAttempt, enqueueAttempt, pendingAttempts, queueStatus, retryAttempts } from './resultQueue'

beforeEach(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  })
  vi.stubGlobal('window', new EventTarget())
})

test('a delayed confirmation preserves newer attempts and another user queue', async () => {
  setSessionLogin('queue-a')
  const first = enqueueAttempt('p1', true, false)
  let resolve!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((r) => { resolve = r })))
  const request = deliverAttempt(first)
  const newer = enqueueAttempt('p1', false, true)
  setSessionLogin('queue-b')
  const other = enqueueAttempt('p2', true, false)
  resolve(new Response(JSON.stringify({ rating_before: 600, rating_after: 610, delta: 10 })))
  await request
  expect(pendingAttempts('queue-a')).toEqual([newer])
  expect(pendingAttempts('queue-b')).toEqual([other])
})

test('an uncertain response retains the same ID for retry', async () => {
  setSessionLogin('queue-retry')
  const details = { ply: 3, played_uci: 'e2e4', first_uci: 'e2e4', revealed: false, elapsed_ms: 340 }
  const entry = enqueueAttempt('p1', false, false, undefined, details)
  const fetch = vi.fn().mockRejectedValueOnce(new Error('Response lost')).mockResolvedValueOnce(
    new Response(JSON.stringify({ rating_before: 600, rating_after: 610, delta: 10 })),
  )
  vi.stubGlobal('fetch', fetch)
  await expect(deliverAttempt(entry)).rejects.toThrow('Response lost')
  expect(pendingAttempts()).toEqual([entry])
  await retryAttempts()
  expect(pendingAttempts()).toEqual([])
  const bodies = fetch.mock.calls.map((call) => JSON.parse(call[1].body))
  expect(bodies).toEqual(Array(2).fill({ client_id: entry.client_id, expected_login: entry.login, solved: false, used_hint: false, details }))
})

test('an in-flight failure result cannot remove the later reveal from the outbox', async () => {
  setSessionLogin('queue-reveal')
  const details = { ply: 3, played_uci: 'e2e4', first_uci: 'e2e4', revealed: false, elapsed_ms: 340 }
  const entry = enqueueAttempt('p1', false, false, undefined, details)
  let resolve!: (value: Response) => void
  const fetch = vi.fn()
    .mockImplementationOnce(() => new Promise<Response>((r) => { resolve = r }))
    .mockRejectedValueOnce(new Error('Offline'))
  vi.stubGlobal('fetch', fetch)
  const first = deliverAttempt(entry)
  const revealed = enqueueAttempt('p1', false, false, entry.client_id, { ...details, revealed: true })
  const updated = deliverAttempt(revealed)
  resolve(new Response(JSON.stringify({ rating_before: 600, rating_after: 590, delta: -10 })))
  await first
  await expect(updated).rejects.toThrow('Offline')
  expect(pendingAttempts()).toEqual([revealed])
  expect(JSON.parse(fetch.mock.calls[1][1].body).details).toEqual({ ...details, revealed: true })
})

test('unavailable storage retains multiple attempts in memory and reports a warning', () => {
  setSessionLogin('queue-no-storage')
  vi.stubGlobal('localStorage', { getItem() { throw new Error('Denied') }, setItem() { throw new Error('Denied') } })
  const first = enqueueAttempt('p1', true, false)
  const second = enqueueAttempt('p2', false, false)
  expect(pendingAttempts()).toEqual([first, second])
  expect(queueStatus('queue-no-storage').warning).toBe(true)
})
