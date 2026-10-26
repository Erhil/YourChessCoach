import { call } from './http'

export interface DayCounts {
  puzzles: number
  cards: number
  lesson_positions: number
  games: number
}
export interface NewAchievement {
  key: string
  title: string
  text: string
  earned_at: string
}
export interface NextAchievement {
  key: string
  title: string
  text: string
  progress: number
  target: number
  /** The word after «из N», genitive plural: «задач», «очков рейтинга». */
  unit?: string
}
export interface Activity {
  /** The local date, YYYY-MM-DD. */
  date: string
  today: DayCounts
  week: { start: string; goal: number; days: boolean[]; active_days: number; met: boolean; streak_weeks: number }
  comeback: boolean
  achievements: { new: NewAchievement[]; next: NextAchievement[] }
}

/** Minutes, as the server expects: local time = UTC - tz. */
export const tz = () => new Date().getTimezoneOffset()

export const getActivity = () => call<Activity>(`/api/activity?tz=${tz()}`)
/** Earned and next achievements; `total` is the size of the catalogue. */
export type Achievements = { earned: NewAchievement[]; next: NextAchievement[]; total: number }

export const getAchievements = () => call<Achievements>(`/api/achievements?tz=${tz()}`)
export const setWeekGoal = (goal: number) => call<void>('/api/activity/goal', { goal })
export const markAchievementsSeen = (keys: string[]) => call<void>('/api/achievements/seen', { keys })

// A user action that counts as activity (a puzzle attempt, a deck answer, a lesson position, a saved game).
const bus = new EventTarget()
export const onActivity = (fn: () => void) => {
  bus.addEventListener('activity', fn)
  return () => bus.removeEventListener('activity', fn)
}
/** The same call; after it succeeds, the activity listeners run. */
export const signalled =
  <A extends unknown[], T>(fn: (...a: A) => Promise<T>) =>
  async (...a: A) => {
    const r = await fn(...a)
    bus.dispatchEvent(new Event('activity'))
    return r
  }
