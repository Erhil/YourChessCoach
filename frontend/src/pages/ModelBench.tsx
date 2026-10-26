import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getPair, getResults, setDefaultModel, vote, type BenchPair, type BenchResults } from '../api/bench'
import { Board } from '../components/Board'
import { CLASS_WORD, toFigurine } from '../chess/notation'
import css from './ModelBench.module.css'

export default function ModelBench() {
  const [pair, setPair] = useState<BenchPair | null>(null)
  const [results, setResults] = useState<BenchResults | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [votes, setVotes] = useState(0)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([getPair(), getResults()]).then(
      ([p, r]) => {
        setPair(p)
        setResults(r)
        setVotes(r.models.reduce((n, m) => n + m.votes, 0) / 2)
      },
      (e: unknown) => setError(e instanceof Error ? e.message : 'Не удалось загрузить сравнение'),
    )
  }, [])

  const choose = async (winner: 'a' | 'b' | 'tie') => {
    if (!pair || busy) return
    setBusy(true)
    try {
      const v = await vote(pair.token, winner)
      setVotes(v.votes)
      const [p, r] = await Promise.all([getPair(), getResults()])
      setPair(p)
      setResults(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить голос')
    } finally {
      setBusy(false)
    }
  }

  const makeDefault = async (model: string) => {
    try {
      await setDefaultModel(model)
      setResults(await getResults())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить модель')
    }
  }

  return (
    <main style={{ padding: 16 }}>
      <Link to="/admin">← Админка</Link>
      <h1>Сравнение моделей</h1>
      {error && <p role="alert">{error}</p>}
      {pair && (
        <div className={css.layout}>
          <div className={css.board}>
            <Board
              position={pair.fen}
              orientation={pair.fen.split(' ')[1] === 'b' ? 'black' : 'white'}
              canMove={false}
              onMove={() => false}
            />
          </div>
          <div>
            <p>
              Ход игрока: {toFigurine(pair.move_san)} — {CLASS_WORD[pair.classification]}.
              {pair.best_move_san && <> Лучший ход: {toFigurine(pair.best_move_san)}</>}
            </p>
            <div className={css.cards}>
              <section className={css.card}>
                <h3>Объяснение A</h3>
                <p>{pair.a.text}</p>
              </section>
              <section className={css.card}>
                <h3>Объяснение B</h3>
                <p>{pair.b.text}</p>
              </section>
            </div>
            <div className={css.buttons}>
              <button onClick={() => void choose('a')} disabled={busy}>
                Лучше A
              </button>
              <button onClick={() => void choose('b')} disabled={busy}>
                Лучше B
              </button>
              <button onClick={() => void choose('tie')} disabled={busy}>
                Одинаково
              </button>
            </div>
            <p className="muted">Голосов: {votes}</p>
          </div>
        </div>
      )}
      {results && (
        <>
          <h2>Результаты</h2>
          <div className={css.tableWrap}>
            <table className={css.table}>
              <thead>
                <tr>
                  <th>Модель</th>
                  <th>Голоса</th>
                  <th>Побед, %</th>
                  <th>Прошли проверку, %</th>
                  <th>Время ответа, с</th>
                  <th>Видеопамять, ГБ</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {results.models.map((m) => (
                  <tr key={m.model} data-testid={`row-${m.model}`}>
                    <td>
                      {m.model === "template" ? "шаблон" : m.model}
                      {m.model === results.default_model && <span className={css.mark}> ✓ по умолчанию</span>}
                    </td>
                    <td>{m.votes}</td>
                    <td>{Math.round(m.win_rate * 100)}</td>
                    <td>{Math.round(m.valid_pct * 100)}</td>
                    <td>{m.mean_seconds.toFixed(1)}</td>
                    <td>{m.vram_gb ?? '—'}</td>
                    <td>
                      {m.model !== results.default_model && (
                        <button onClick={() => void makeDefault(m.model)}>Сделать моделью по умолчанию</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  )
}
