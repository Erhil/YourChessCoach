import { useEffect, useState } from 'react'
import { analyze } from '../api/client'
import css from './EvalBar.module.css'

type Score = { cp: number | null; mate: number | null }

/** White win share in percent, 0..100. */
export function whiteShare({ cp, mate }: Score): number {
  if (mate !== null) return mate > 0 ? 100 : 0
  return 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * (cp ?? 0))) - 1)
}

/** Short text for a beginner. No raw centipawns. */
export function evalText({ cp, mate }: Score): string {
  if (mate !== null) return `Мат в ${Math.abs(mate)}`
  const v = cp ?? 0
  const a = Math.abs(v)
  const side = v > 0 ? 'белых' : 'чёрных'
  if (a < 50) return 'Примерно равно'
  if (a < 150) return `Чуть лучше у ${side}`
  if (a < 400) return `Лучше у ${side}`
  return v > 0 ? 'Белые выигрывают' : 'Чёрные выигрывают'
}

export function EvalBar({ fen }: { fen: string }) {
  const [score, setScore] = useState<Score | null>(null)

  useEffect(() => {
    let stale = false
    analyze(fen, 300)
      .then((a) => {
        if (!stale) setScore(a.lines[0]?.score ?? null)
      })
      .catch(() => {
        if (!stale) setScore(null)
      })
    return () => {
      stale = true
    }
  }, [fen])

  return (
    <div className={css.root} data-testid="eval">
      <div className={css.bar} role="img" aria-label="Шкала оценки">
        <div className={css.fill} style={{ width: `${score ? whiteShare(score) : 50}%` }} />
      </div>
      <p className={css.text}>{score ? evalText(score) : 'Считаю…'}</p>
    </div>
  )
}
