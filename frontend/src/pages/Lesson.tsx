import { marked } from 'marked'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  getHealth,
  getLesson,
  getLessons,
  sendLessonPosition,
  type Lesson as LessonData,
  type LessonSummary,
} from '../api/client'
import { AskCoach } from '../lessons/AskCoach'
import { LineViewer } from '../lessons/LineViewer'
import { LessonPosition } from '../lessons/LessonPosition'
import css from './Lesson.module.css'

export default function Lesson() {
  const { slug = '' } = useParams()
  const [lesson, setLesson] = useState<LessonData | null>(null)
  const [all, setAll] = useState<LessonSummary[]>([])
  const [solved, setSolved] = useState<number[]>([])
  const [error, setError] = useState(false)
  const [llm, setLlm] = useState(false)

  useEffect(() => {
    let live = true
    getLesson(slug).then(
      (l) => {
        if (!live) return
        setError(false)
        setLesson(l)
        setSolved(l.solved ?? [])
      },
      () => live && setError(true),
    )
    getLessons().then(
      (l) => live && setAll(l),
      () => {},
    )
    getHealth().then(
      (h) => live && setLlm(!!h.llm?.enabled && h.llm.available),
      () => {},
    )
    return () => {
      live = false
    }
  }, [slug])

  if (error) {
    return (
      <p>
        Не удалось загрузить урок. <Link to="/lessons">К списку уроков</Link>
      </p>
    )
  }
  if (!lesson || lesson.slug !== slug) return <p className="muted">Загружаю урок…</p>

  const onSolved = (i: number) => {
    setSolved((s) => (s.includes(i) ? s : [...s, i]))
    sendLessonPosition(slug, i).then(
      (r) => setSolved(r.solved),
      () => {},
    )
  }
  const next = all.filter((l) => l.number > lesson.number).sort((a, b) => a.number - b.number)[0]
  let n = 0
  return (
    <article className={css.lesson}>
      {lesson.segments.map((s, i) => {
        if (s.type === 'markdown') {
          const html = marked.parse(s.text, { async: false })
          return <div key={i} className={css.md} dangerouslySetInnerHTML={{ __html: html }} />
        }
        if (s.type === 'line') return <LineViewer key={`${slug}-${i}`} block={s} />
        const index = n++
        return (
          <LessonPosition
            key={`${slug}-${i}`}
            index={index}
            block={s}
            solved={solved.includes(index)}
            onSolved={onSolved}
          />
        )
      })}
      {llm && <AskCoach slug={slug} positions={n} />}
      <nav className={css.nav}>
        {next && <Link to={`/lessons/${next.slug}`}>Следующий урок: {next.title}</Link>}
        <Link to="/lessons">К списку уроков</Link>
      </nav>
    </article>
  )
}
