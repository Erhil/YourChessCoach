import type { NewAchievement } from '../api/activity'
import type { NextMistake } from '../api/mistakes'
import type { Progress, WeekSummary } from '../api/progress'

/** The rating of a new user: START_RATING in backend/app/puzzles/rating.py. */
export const START_RATING = 600
const DAY = 86_400_000

/** «1,2»: the Russian decimal comma. */
export const comma = (x: number, digits = 1) => x.toFixed(digits).replace('.', ',')
/** «+12», «−0,4», «0». */
export const signed = (x: number, digits = 0) => (x > 0 ? '+' : x < 0 ? '−' : '') + comma(Math.abs(x), digits)
/** «25.10» from an ISO date or time. */
export const dayMonth = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`

/**
 * The rating change and its period: in the last 7 days, or since the first attempt when it is less than 7 days old.
 * The history holds the last HISTORY_LIMIT (200, backend/app/progress/routes.py) attempts: it holds the first
 * attempt only when it is not cut (attempts <= its length). A cut history inside the 7 days counts from its first point.
 */
export function ratingChange(p: Progress['puzzles'], now: Date): { value: number; since: string } {
  const h = p.history
  if (!h.length) return { value: 0, since: 'за 7 дней' }
  const last = h.at(-1)!.rating
  const before = h.filter((x) => Date.parse(x.at) < now.getTime() - 7 * DAY).at(-1)
  if (before) return { value: last - before.rating, since: 'за 7 дней' }
  if (p.attempts <= h.length) return { value: last - START_RATING, since: 'с первой задачи' }
  return { value: last - h[0].rating, since: `с ${dayMonth(h[0].at)}` }
}

/** The latest week with a blunder rate, its change and the week it is compared to (the week before it that has one). */
export function blunderTrend(weeks: WeekSummary[]) {
  const known = weeks.filter((w) => w.blunders_per_10_moves !== null)
  const latest = known.at(-1)
  if (!latest) return null
  const prev = known.at(-2)
  const value = latest.blunders_per_10_moves!
  // Rounded as shown, so «0,0» is never called better or worse.
  const change = prev ? Math.round(10 * (value - prev.blunders_per_10_moves!)) / 10 : null
  const than = !prev ? '' : Date.parse(latest.start) - Date.parse(prev.start) === 7 * DAY ? 'неделей раньше' : `в неделю с ${dayMonth(prev.start)}`
  return { latest, value, change, than, known }
}

/** Up to 4 themes, the highest rating first; themes with 3 attempts or more, else all themes. */
export function topThemes(themes: Progress['themes']) {
  const sure = themes.filter((t) => t.attempts >= 3)
  return { items: [...(sure.length ? sure : themes)].sort((a, b) => b.rating - a.rating).slice(0, 4), early: !sure.length }
}

/** Cards left today: the due ones, but not more than the daily limit allows (as on the deck page). */
export const deckLeft = (n: NextMistake) => Math.max(0, Math.min(n.due, n.today.limit - n.today.reviewed))

/** The achievement earned last. */
export const lastEarned = (items: NewAchievement[]) =>
  items.reduce<NewAchievement | null>((a, b) => (!a || b.earned_at > a.earned_at ? b : a), null)
