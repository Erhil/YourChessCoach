/** Error with the HTTP status, so callers can tell 401 and 503 from other failures. */
export class HttpError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

// Auth, and admin calls (admin only) handle 401 themselves; every other 401 means "log in again".
const OWN_401 = ['/api/auth/', '/api/admin/']
let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  onUnauthorized = fn
}

/** GET without a body, POST JSON with a body. Throws the server `detail` text when there is one. */
export async function call<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    if (res.status === 401 && !OWN_401.some((p) => url.startsWith(p))) onUnauthorized?.()
    const detail = ((await res.json().catch(() => null)) as { detail?: unknown } | null)?.detail
    throw new HttpError(typeof detail === 'string' ? detail : `${url}: ${res.status}`, res.status)
  }
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}
