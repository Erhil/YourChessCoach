import { afterEach, expect, test, vi } from 'vitest'
import { call, HttpError, setUnauthorizedHandler } from './http'
import { sessionKey, setSessionLogin } from '../auth/session'

const reply = (status: number, body?: unknown) =>
  vi.stubGlobal('fetch', vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status })))

afterEach(() => {
  setUnauthorizedHandler(null)
  vi.unstubAllGlobals()
})

test('a 401 on a data call calls the handler', async () => {
  const handler = vi.fn()
  setUnauthorizedHandler(handler)
  reply(401, { detail: 'x' })
  await expect(call('/api/progress')).rejects.toBeInstanceOf(HttpError)
  expect(handler).toHaveBeenCalledOnce()
})

test('a 401 on auth and admin calls does not call the handler', async () => {
  const handler = vi.fn()
  setUnauthorizedHandler(handler)
  reply(401, { detail: 'Неверный логин или токен' })
  for (const url of ['/api/auth/login', '/api/admin/users']) {
    await expect(call(url, {})).rejects.toMatchObject({ status: 401 })
  }
  expect(handler).not.toHaveBeenCalled()
})

test('an empty 204 answer is fine', async () => {
  reply(204)
  await expect(call('/api/auth/logout', {})).resolves.toBeUndefined()
})

test('device storage keys include the login', () => {
  setSessionLogin('anna')
  expect(sessionKey('play.game')).toBe('play.game:anna')
})
