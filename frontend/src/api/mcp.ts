import { call, HttpError } from './http'

export interface McpKeyState {
  exists: boolean
  created_at: string | null
}
export interface Plan {
  created_at: string
  summary: string
  focus_themes: string[]
  lessons: string[]
  openings: string[]
}

/** DELETE with no body; `call` only does GET and POST. */
async function del(url: string): Promise<void> {
  const res = await fetch(url, { method: 'DELETE' })
  if (!res.ok) {
    const detail = ((await res.json().catch(() => null)) as { detail?: unknown } | null)?.detail
    throw new HttpError(typeof detail === 'string' ? detail : `${url}: ${res.status}`, res.status)
  }
}

export const getMcpKey = () => call<McpKeyState>('/api/mcp-key')
export const createMcpKey = () => call<{ key: string }>('/api/mcp-key', {})
export const deleteMcpKey = () => del('/api/mcp-key')
export const getPlan = () => call<{ plan: Plan | null }>('/api/plan').then((r) => r.plan)
export const deleteUserMcpKey = (id: number) => del(`/api/admin/users/${id}/mcp-key`)

/** The Claude Code command that connects the senior coach in every folder (--scope user). */
export const mcpCommand = (address: string, key: string) =>
  `claude mcp add --scope user --transport http chess ${address} --header "Authorization: Bearer ${key}"`

/** The first plan lesson that is not completed, or null. */
export function planLesson<T extends { slug: string; completed?: boolean }>(plan: Plan, lessons: T[]): T | null {
  for (const slug of plan.lessons) {
    const l = lessons.find((x) => x.slug === slug)
    if (l && !l.completed) return l
  }
  return null
}
