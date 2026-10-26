import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getLessons, type LessonSummary } from '../api/client'
import { nextLesson } from '../lessons/nextLesson'
import css from './Lessons.module.css'

const SECTIONS = ['Дебюты: за белых', 'Дебюты: за чёрных', 'Дебюты: ловушки']

export default function Lessons() {
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    getLessons().then(setLessons, () => setError(true))
  }, [])

  if (error) return <p>Не удалось загрузить уроки.</p>
  if (!lessons) return <p className="muted">Загружаю уроки…</p>
  const next = nextLesson(lessons)
  const plain = lessons.filter((l) => !l.section)
  const levels = [...new Set(plain.map((l) => l.level))].sort()
  const known = SECTIONS.filter((s) => lessons.some((l) => l.section === s))
  const sections = [...known, ...new Set(lessons.map((l) => l.section ?? '').filter((s) => s && !SECTIONS.includes(s)))]
  const groups = [
    ...levels.map((level) => ({
      key: `level-${level}`,
      title: `Уровень ${level}`,
      items: plain.filter((l) => l.level === level),
    })),
    ...sections.map((s) => ({
      key: s,
      title: s,
      items: lessons.filter((l) => l.section === s),
    })),
  ]
  return (
    <>
      <h1>Уроки</h1>
      {next && (
        <p>
          Следующий урок: <Link to={`/lessons/${next.slug}`}>{next.title}</Link>
        </p>
      )}
      {groups.map((g) => (
        <section key={g.key}>
          <h2>{g.title}</h2>
          <ul className={css.list}>
            {g.items
              .sort((a, b) => a.number - b.number)
              .map((l) => (
                <li key={l.slug}>
                  <Link to={`/lessons/${l.slug}`} className={css.card}>
                    <strong>{l.title}</strong>
                    <span className="muted">
                      {l.solved ?? 0} из {l.positions} позиций
                      {l.completed && ' · пройден ✓'}
                    </span>
                  </Link>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </>
  )
}
