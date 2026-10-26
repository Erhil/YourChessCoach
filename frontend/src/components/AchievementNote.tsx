import { useEffect, useRef, useState } from 'react'
import { getActivity, markAchievementsSeen, onActivity, type NewAchievement } from '../api/activity'
import { popClass } from '../motion'
import css from './Achievements.module.css'

const SHOW_MS = 6000

/** A short message about new achievements; it checks on mount and after each user action. */
export default function AchievementNote() {
  const [items, setItems] = useState<NewAchievement[]>([])
  // Each new batch changes the stamp: it restarts the hide timer and the animation.
  const [stamp, setStamp] = useState(0)
  // Keys already shown: an overlapping load does not show or post them again.
  const shown = useRef(new Set<string>())
  useEffect(() => {
    const load = () =>
      getActivity().then(
        (a) => {
          const fresh = (a.achievements?.new ?? []).filter((x) => !shown.current.has(x.key))
          if (!fresh.length) return
          for (const x of fresh) shown.current.add(x.key)
          setItems((prev) => [...prev, ...fresh])
          setStamp((s) => s + 1)
          markAchievementsSeen(fresh.map((x) => x.key)).catch(() => {})
        },
        () => {},
      )
    void load()
    return onActivity(load)
  }, [])
  useEffect(() => {
    if (!stamp) return
    const t = setTimeout(() => setItems([]), SHOW_MS)
    return () => clearTimeout(t)
  }, [stamp])
  if (!items.length) return null
  const more = items.length - 3
  return (
    <div key={stamp} role="status" className={`${css.note} ${popClass()}`} data-testid="achievement-note">
      <div className={css.body}>
        {items.length === 1 ? (
          <>
            <p><strong>Достижение: {items[0].title}</strong></p>
            <p>{items[0].text}</p>
          </>
        ) : (
          <p>
            <strong>Новые достижения: {items.slice(0, 3).map((x) => x.title).join(', ')}</strong>
            {more > 0 && ` и ещё ${more}`}
          </p>
        )}
      </div>
      <button type="button" className={css.close} aria-label="Закрыть" onClick={() => setItems([])}>
        ✕
      </button>
    </div>
  )
}
