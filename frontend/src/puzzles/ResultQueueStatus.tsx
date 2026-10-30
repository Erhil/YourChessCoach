import { useEffect, useReducer } from 'react'
import { queueStatus, RESULT_QUEUE_EVENT, retryAttempts } from './resultQueue'

export default function ResultQueueStatus({ login }: { login: string }) {
  const [, refresh] = useReducer((n: number) => n + 1, 0)
  useEffect(() => {
    const retry = () => { void retryAttempts() }
    window.addEventListener(RESULT_QUEUE_EVENT, refresh)
    window.addEventListener('online', retry)
    retry()
    return () => {
      window.removeEventListener(RESULT_QUEUE_EVENT, refresh)
      window.removeEventListener('online', retry)
    }
  }, [login])
  const { count, warning, failed } = queueStatus(login)
  if (!count && !warning) return null
  return <div role="status" data-testid="puzzle-save-status">
    {warning && <p>Хранилище браузера недоступно. Несохранённые результаты задач могут пропасть после перезагрузки.</p>}
    {count > 0 && <p>{failed ? 'Не удалось сохранить результаты задач.' : 'Результаты задач ещё не подтверждены сервером.'} Осталось: {count}.</p>}
    {count > 0 && <button type="button" onClick={() => { void retryAttempts() }}>Повторить сохранение задач</button>}
  </div>
}
