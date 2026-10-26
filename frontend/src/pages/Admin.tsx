import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  adminCreateUser, adminLogin, adminLogout, adminResetToken, adminUserProgress, adminUsers, type AdminUser,
} from '../api/auth.ts'
import { HttpError } from '../api/http.ts'
import { deleteUserMcpKey } from '../api/mcp.ts'
import type { Progress } from '../api/progress.ts'
import { ProgressView } from '../components/ProgressView.tsx'
import { TokenBox } from '../components/TokenBox.tsx'
import css from './Admin.module.css'

type Gate = 'loading' | 'login' | 'unset' | 'ok'
const message = (e: unknown) => (e instanceof Error ? e.message : 'Что-то пошло не так')
const seen = (iso: string | null) => (iso ? new Date(iso).toLocaleString('ru-RU') : '—')

function AdminLogin({ unset, onDone }: { unset: boolean; onDone: () => void }) {
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [noToken, setNoToken] = useState(unset)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await adminLogin(token.trim())
      onDone()
    } catch (err) {
      if (err instanceof HttpError && err.status === 503) setNoToken(true)
      else setError(message(err))
    }
  }
  return (
    <form className={css.form} onSubmit={submit}>
      <h1>Админка</h1>
      {noToken ? (
        <p role="alert" className={css.error}>ADMIN_TOKEN не задан в .env. Добавьте его и перезапустите сервер.</p>
      ) : (
        <>
          <label>
            Токен администратора
            <input
              className={css.input}
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              required
            />
          </label>
          {error && <p role="alert" className={css.error}>{error}</p>}
          <button type="submit">Войти</button>
        </>
      )}
      <Link to="/">← К приложению</Link>
    </form>
  )
}

export default function Admin() {
  const [gate, setGate] = useState<Gate>('loading')
  const [users, setUsers] = useState<AdminUser[]>([])
  const [error, setError] = useState<string | null>(null)
  const [shown, setShown] = useState<{ login: string; token: string } | null>(null)
  const [newLogin, setNewLogin] = useState('')
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [keyId, setKeyId] = useState<number | null>(null)
  const [viewing, setViewing] = useState<{ login: string; data: Progress } | null>(null)

  const load = useCallback(
    () =>
      adminUsers().then(
        (list) => {
          setUsers(list)
          setGate('ok')
        },
        (e: unknown) => setGate(e instanceof HttpError && e.status === 503 ? 'unset' : 'login'),
      ),
    [],
  )
  useEffect(() => {
    load()
  }, [load])

  const guard = async (fn: () => Promise<void>) => {
    setError(null)
    try {
      await fn()
    } catch (e) {
      if (e instanceof HttpError && e.status === 401) setGate('login')
      else setError(message(e))
    }
  }

  const create = (e: FormEvent) => {
    e.preventDefault()
    void guard(async () => {
      const r = await adminCreateUser(newLogin.trim())
      setShown({ login: r.login, token: r.token })
      setNewLogin('')
      setUsers(await adminUsers())
    })
  }
  const reset = (u: AdminUser) =>
    guard(async () => {
      const r = await adminResetToken(u.id)
      setConfirmId(null)
      setShown({ login: u.login, token: r.token })
    })
  const revoke = (u: AdminUser) =>
    guard(async () => {
      await deleteUserMcpKey(u.id)
      setKeyId(null)
      setUsers(await adminUsers())
    })
  const progress = (u: AdminUser) =>
    guard(async () => setViewing({ login: u.login, data: await adminUserProgress(u.id) }))
  const leave = async () => {
    await adminLogout().catch(() => undefined)
    setShown(null)
    setViewing(null)
    setGate('login')
  }

  if (gate === 'loading') return null
  if (gate !== 'ok') {
    return (
      <main className={css.page}>
        <AdminLogin unset={gate === 'unset'} onDone={load} />
      </main>
    )
  }
  return (
    <main className={css.page}>
      <h1>Админка</h1>
      <div className={css.row}>
        <Link to="/">← К приложению</Link>
        <Link to="/admin/bench">Сравнение моделей</Link>
        <button type="button" onClick={leave}>Выйти из админки</button>
      </div>
      {error && <p role="alert" className={css.error}>{error}</p>}
      {shown && <TokenBox login={shown.login} token={shown.token} onClose={() => setShown(null)} />}

      <h2>Создать пользователя</h2>
      <form className={css.row} onSubmit={create}>
        <input
          className={css.input}
          aria-label="Логин нового пользователя"
          placeholder="логин"
          value={newLogin}
          onChange={(e) => setNewLogin(e.target.value)}
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          required
        />
        <button type="submit">Создать пользователя</button>
      </form>

      <h2>Пользователи</h2>
      {users.length === 0 ? (
        <p className="muted">Пользователей пока нет.</p>
      ) : (
        <table className={css.table}>
          <thead>
            <tr>
              <th>Логин</th><th>Последний визит</th><th>Партий</th><th>Рейтинг задач</th>
              <th>Решено задач</th><th>Ошибок к повторению</th><th>Ошибок усвоено</th><th>Уроков пройдено</th><th>Ключ MCP</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} data-testid={`user-${u.login}`}>
                <td data-label="Логин"><strong>{u.login}</strong></td>
                <td data-label="Последний визит">{seen(u.last_seen_at)}</td>
                <td data-label="Партий">{u.games}</td>
                <td data-label="Рейтинг задач">{Math.round(u.puzzle_rating)}</td>
                <td data-label="Решено задач">{u.puzzles_solved}</td>
                <td data-label="Ошибок к повторению">{u.mistakes_due}</td>
                <td data-label="Ошибок усвоено">{u.mistakes_learned}</td>
                <td data-label="Уроков пройдено">{u.lessons_done}</td>
                <td data-label="Ключ MCP">{u.mcp_key ? 'есть' : 'нет'}</td>
                <td className={css.actions}>
                  {keyId === u.id ? (
                    <div role="group" aria-label={`Отзыв ключа ${u.login}`}>
                      <p>Ключ MCP перестанет работать</p>
                      <div className={css.row}>
                        <button type="button" onClick={() => revoke(u)}>Да, отозвать</button>
                        <button type="button" onClick={() => setKeyId(null)}>Отмена</button>
                      </div>
                    </div>
                  ) : confirmId === u.id ? (
                    <div role="group" aria-label={`Сброс токена ${u.login}`}>
                      <p>Старый токен перестанет работать, пользователь выйдет на всех устройствах</p>
                      <div className={css.row}>
                        <button type="button" onClick={() => reset(u)}>Да, сбросить</button>
                        <button type="button" onClick={() => setConfirmId(null)}>Отмена</button>
                      </div>
                    </div>
                  ) : (
                    <div className={css.row}>
                      <button type="button" onClick={() => progress(u)}>Прогресс</button>
                      <button type="button" onClick={() => setConfirmId(u.id)}>Сбросить токен</button>
                      {u.mcp_key && <button type="button" onClick={() => setKeyId(u.id)}>Отозвать ключ</button>}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {viewing && (
        <section aria-label="Прогресс пользователя">
          <h2>Прогресс: {viewing.login}</h2>
          <ProgressView d={viewing.data} />
          <button type="button" onClick={() => setViewing(null)}>Закрыть прогресс</button>
        </section>
      )}
    </main>
  )
}
