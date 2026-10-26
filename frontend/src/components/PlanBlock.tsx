import { Link } from 'react-router-dom'
import type { LessonSummary, PuzzleTheme } from '../api/client'
import type { Plan } from '../api/mcp'
import type { PuzzleOpening } from '../api/openings'
import css from './ProgressDetails.module.css'

const linkStyle = { marginRight: 12, display: 'inline-flex', alignItems: 'center', minHeight: 44 } as const
export const nameOf = (list: { key: string; name: string }[], key: string) => list.find((x) => x.key === key)?.name ?? key

/** «План от старшего тренера», or a hint to connect the senior coach. */
export default function PlanBlock({ plan, themes, openings, lessons }: {
  plan: Plan | null
  themes: PuzzleTheme[]
  openings: PuzzleOpening[]
  lessons: LessonSummary[] | null
}) {
  if (!plan)
    return (
      <p className="muted">
        Подключите старшего тренера в <Link to="/profile#settings" style={{ ...linkStyle, marginRight: 0 }}>настройках профиля</Link>, чтобы получить план
      </p>
    )
  return (
    <section aria-label="План от старшего тренера" className={css.step} style={{ display: 'block', marginBottom: 16 }}>
      <h2>План от старшего тренера</h2>
      <p className="muted">{new Date(plan.created_at).toLocaleDateString('ru-RU')}</p>
      <p style={{ whiteSpace: 'pre-line' }}>{plan.summary}</p>
      {plan.focus_themes.length > 0 && (
        <p>
          Темы:{' '}
          {plan.focus_themes.map((k) => (
            <Link key={k} to={`/puzzles?theme=${encodeURIComponent(k)}`} style={linkStyle}>{nameOf(themes, k)}</Link>
          ))}
        </p>
      )}
      {plan.lessons.length > 0 && (
        <p>
          Уроки:{' '}
          {plan.lessons.map((s) => (
            <Link key={s} to={`/lessons/${s}`} style={linkStyle}>{lessons?.find((l) => l.slug === s)?.title ?? s}</Link>
          ))}
        </p>
      )}
      {plan.openings.length > 0 && (
        <p>
          Дебюты:{' '}
          {plan.openings.map((k) => (
            <Link key={k} to={`/puzzles?opening=${encodeURIComponent(k)}`} style={linkStyle}>{nameOf(openings, k)}</Link>
          ))}
        </p>
      )}
    </section>
  )
}
