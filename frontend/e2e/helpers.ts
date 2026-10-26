import type { APIRequest, APIRequestContext } from '@playwright/test'
import { ADMIN_TOKEN } from './constants.ts'

export const uniqueLogin = (prefix: string) => `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`

/** Admin API session. Cookies stay in the returned context. */
export async function adminApi(factory: APIRequest, baseURL: string): Promise<APIRequestContext> {
  const ctx = await factory.newContext({ baseURL })
  const res = await ctx.post('/api/admin/login', { data: { token: ADMIN_TOKEN } })
  if (!res.ok()) throw new Error(`admin login failed: ${res.status()}`)
  return ctx
}

export async function createUser(admin: APIRequestContext, login: string) {
  const res = await admin.post('/api/admin/users', { data: { login } })
  if (!res.ok()) throw new Error(`create user failed: ${res.status()}`)
  return (await res.json()) as { id: number; login: string; token: string }
}

/** A user API session: creates the user and logs in. */
export async function userApi(factory: APIRequest, baseURL: string, admin: APIRequestContext, prefix: string) {
  const user = await createUser(admin, uniqueLogin(prefix))
  const ctx = await factory.newContext({ baseURL })
  const res = await ctx.post('/api/auth/login', { data: { login: user.login, token: user.token } })
  if (!res.ok()) throw new Error(`login failed: ${res.status()}`)
  return { ...user, ctx }
}
