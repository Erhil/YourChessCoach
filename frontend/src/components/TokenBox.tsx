import { useRef, useState } from 'react'
import css from '../pages/Admin.module.css'

/** Shows a new token once, with a copy button. The text is selected when the Clipboard API is not there. */
export function TokenBox({ login, token, onClose, label }: { login: string; token: string; onClose: () => void; label?: string }) {
  const ref = useRef<HTMLElement>(null)
  const [note, setNote] = useState('')
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(token)
      setNote('Скопировано')
    } catch {
      const range = document.createRange()
      range.selectNodeContents(ref.current!)
      const sel = window.getSelection()
      sel?.removeAllRanges()
      sel?.addRange(range)
      setNote('Текст выделен, скопируйте его вручную')
    }
  }
  return (
    <section className={css.tokenBox} aria-label="Новый токен">
      <p>{label ?? `Токен пользователя ${login}:`}</p>
      <code ref={ref} className={css.token} data-testid="token">{token}</code>
      <p className={css.warn}>Токен показывается один раз</p>
      <div className={css.row}>
        <button type="button" onClick={copy}>Скопировать</button>
        <button type="button" onClick={onClose}>Закрыть</button>
      </div>
      {note && <p role="status" className="muted">{note}</p>}
    </section>
  )
}
