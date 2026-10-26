import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { login } from '../api/auth.ts'
import css from './Login.module.css'

type From = { pathname: string; search?: string; hash?: string }

export default function Login({ user, onLogin }: { user: string | null; onLogin: (login: string) => void }) {
  const from = (useLocation().state as { from?: From } | null)?.from
  const [name, setName] = useState('')
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) {
    const to = from && from.pathname !== '/login' ? `${from.pathname}${from.search ?? ''}${from.hash ?? ''}` : '/'
    return <Navigate to={to} replace />
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await login(name.trim(), token.trim())
      onLogin(r.login)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось войти')
      setBusy(false)
    }
  }

  return (
    <main className={css.page}>
      <form className={css.form} onSubmit={submit}>
        <h1>Вход</h1>
        <label>
          Логин
          <input
            className={css.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="username"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            required
          />
        </label>
        <label>
          Токен
          <input
            className={css.input}
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoComplete="current-password"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            required
          />
        </label>
        {error && <p role="alert" className={css.error}>{error}</p>}
        <button type="submit" className={css.submit} disabled={busy}>Войти</button>
      </form>
    </main>
  )
}
