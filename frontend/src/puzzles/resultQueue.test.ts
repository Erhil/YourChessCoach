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
  const entry = enqueueAttempt('p1', true, false)
  const fetch = vi.fn().mockRejectedValueOnce(new Error('Response lost')).mockResolvedValueOnce(
    new Response(JSON.stringify({ rating_before: 600, rating_after: 610, delta: 10 })),
  )
  vi.stubGlobal('fetch', fetch)
  await expect(deliverAttempt(entry)).rejects.toThrow('Response lost')
  expect(pendingAttempts()).toEqual([entry])
  await retryAttempts()
  expect(pendingAttempts()).toEqual([])
  expect(fetch.mock.calls.map((call) => JSON.parse(call[1].body).client_id)).toEqual([entry.client_id, entry.client_id])
})

test('unavailable storage retains multiple attempts in memory and reports a warning', () => {
  setSessionLogin('queue-no-storage')
  vi.stubGlobal('localStorage', { getItem() { throw new Error('Denied') }, setItem() { throw new Error('Denied') } })
  const first = enqueueAttempt('p1', true, false)
  const second = enqueueAttempt('p2', false, false)
  expect(pendingAttempts()).toEqual([first, second])
  expect(queueStatus('queue-no-storage').warning).toBe(true)
})
