import type { NextAchievement } from '../api/activity'
import css from './Achievements.module.css'
import tcss from './Today.module.css'

/** The nearest achievements (at most 3) with progress «36 из 100 очков рейтинга»; a goal of 1 has no bar. Hidden when there are none. */
export default function NextAchievements({ items }: { items: NextAchievement[] }) {
  if (!items.length) return null
  return (
    <section aria-label="Ближайшие достижения" className={tcss.card}>
      <h2>Ближайшие достижения</h2>
      <ul className={css.list}>
        {items.slice(0, 3).map((a) => {
          const done = Math.min(a.progress, a.target)
          return (
            <li key={a.key}>
              <p><strong>{a.title}</strong></p>
              <p className="muted">{a.text}</p>
              {a.target > 1 && (
                <div className={css.row}>
                  <div
                    className={css.bar}
                    role="progressbar"
                    aria-label={a.title}
                    aria-valuemin={0}
                    aria-valuemax={a.target}
                    aria-valuenow={done}
                  >
                    <span className={css.fill} style={{ width: `${(100 * done) / a.target}%` }} />
                  </div>
                  <span className="muted">
                    {done} из {a.target}
                    {a.unit && ` ${a.unit}`}
                  </span>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
