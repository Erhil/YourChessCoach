import type { NewAchievement } from '../api/activity'
import css from './Achievements.module.css'
import tcss from './Today.module.css'

/** The earned achievements with the local date. */
export default function EarnedAchievements({ items }: { items: NewAchievement[] }) {
  return (
    <section aria-label="Достижения" className={tcss.card}>
      <h2>Достижения</h2>
      {items.length === 0 ? (
        <p className="muted">Пока нет полученных достижений.</p>
      ) : (
        <ul className={css.list}>
          {items.map((a) => (
            <li key={a.key}>
              <p>
                <strong>{a.title}</strong> <span className="muted">{new Date(a.earned_at).toLocaleDateString('ru-RU')}</span>
              </p>
              <p className="muted">{a.text}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
