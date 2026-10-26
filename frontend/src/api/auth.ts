import { call } from './http'
import type { Progress } from './progress'

export interface AdminUser {
  id: number
  login: string
  created_at: string
  last_seen_at: string | null
  games: number
  puzzle_rating: number
  puzzles_solved: number
  mistakes_due: number
  mistakes_learned: number
  lessons_done: number
  mcp_key: boolean
}

export const login = (login: string, token: string) => call<{ login: string }>('/api/auth/login', { login, token })
export const logout = () => call<void>('/api/auth/logout', {})
export const me = () => call<{ login: string }>('/api/auth/me')

export const adminLogin = (token: string) => call<void>('/api/admin/login', { token })
export const adminLogout = () => call<void>('/api/admin/logout', {})
export const adminUsers = () => call<AdminUser[]>('/api/admin/users')
export const adminCreateUser = (login: string) =>
  call<{ id: number; login: string; token: string }>('/api/admin/users', { login })
export const adminResetToken = (id: number) => call<{ token: string }>(`/api/admin/users/${id}/token`, {})
export const adminUserProgress = (id: number) => call<Progress>(`/api/admin/users/${id}/progress`)
