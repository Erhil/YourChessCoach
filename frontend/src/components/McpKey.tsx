import { useCallback, useEffect, useState } from 'react'
import { createMcpKey, deleteMcpKey, getMcpKey, mcpCommand, type McpKeyState } from '../api/mcp.ts'
import css from '../pages/Admin.module.css'
import { TokenBox } from './TokenBox.tsx'

type Ask = 'replace' | 'delete' | null

/** Settings section: create, replace and delete the personal MCP key of the senior coach. */
export function McpKey() {
  const [state, setState] = useState<McpKeyState | null>(null)
  const [key, setKey] = useState<string | null>(null)
  const [ask, setAsk] = useState<Ask>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const load = useCallback(() => getMcpKey().then(setState, (e: Error) => setError(e.message)), [])
  useEffect(() => {
    void load()
  }, [load])

  const run = async (fn: () => Promise<void>) => {
    setError(null)
    setAsk(null)
    try {
      await fn()
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Что-то пошло не так')
    }
  }
  const create = () => run(async () => setKey((await createMcpKey()).key))
  const remove = () =>
    run(async () => {
      await deleteMcpKey()
      setKey(null)
    })

  const address = `${window.location.origin}/mcp`
  const command = mcpCommand(address, key ?? '<ключ>')
  const copyCommand = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setNote('Команда скопирована')
    } catch {
      setNote('Не удалось скопировать, выделите команду вручную')
    }
  }
  const confirm = (text: string, yes: string, action: () => void) => (
    <div role="group" aria-label={text}>
      <p>{text}</p>
      <div className={css.row}>
        <button type="button" onClick={action}>{yes}</button>
        <button type="button" onClick={() => setAsk(null)}>Отмена</button>
      </div>
    </div>
  )

  return (
    <section aria-label="Старший тренер (MCP)">
      <h2>Старший тренер (MCP)</h2>
      <p>Большая модель на вашем компьютере разбирает ваши партии и составляет план.</p>
      {state && (
        <p data-testid="mcp-state">
          {state.exists ? `Ключ создан ${state.created_at ? new Date(state.created_at).toLocaleDateString('ru-RU') : ''}` : 'Ключа нет'}
        </p>
      )}
      {error && <p role="alert" className={css.error}>{error}</p>}
      {key && <TokenBox login="" label="Ключ MCP:" token={key} onClose={() => setKey(null)} />}
      {ask === 'replace' && confirm('Старый ключ перестанет работать', 'Да, заменить', create)}
      {ask === 'delete' && confirm('Ключ будет удалён, старший тренер потеряет доступ', 'Да, удалить', remove)}
      {!ask && state && (
        <div className={css.row}>
          {state.exists ? (
            <>
              <button type="button" onClick={() => setAsk('replace')}>Заменить ключ</button>
              <button type="button" onClick={() => setAsk('delete')}>Удалить ключ</button>
            </>
          ) : (
            <button type="button" onClick={create}>Создать ключ</button>
          )}
        </div>
      )}
      <details>
        <summary style={{ minHeight: 44, display: 'flex', alignItems: 'center' }}>Как подключить</summary>
        <p>Адрес MCP этого сервера: <code>{address}</code></p>
        <p>Команда для Claude Code:</p>
        <code className={css.token} data-testid="mcp-command">{command}</code>
        <div className={css.row}>
          <button type="button" onClick={copyCommand}>Скопировать команду</button>
        </div>
        {note && <p role="status" className="muted">{note}</p>}
      </details>
    </section>
  )
}
