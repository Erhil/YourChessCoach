import type { DayCounts } from '../api/activity'
import { sessionKey } from '../auth/session'

export type TaskKind = 'cards' | 'puzzles' | 'lesson' | 'game'
export interface Task {
  kind: TaskKind
  to: string
  text: string
  time: string
  /** Capped at `target`. */
  done: number
  target: number
}
export interface TaskInput {
  today: DayCounts
  /** Deck cards due now. */
  due: number
  /** The puzzles link and text, as the page chooses the theme. */
  puzzles: { to: string; text: string }
  lesson: { slug: string; title: string } | null
}

const task = (kind: TaskKind, to: string, text: string, time: string, done: number, target: number): Task => ({
  kind, to, text, time, target, done: Math.min(done, target),
})

/** Candidates in order: cards (only when there are any), puzzles, the next lesson, a game. */
export function candidates({ today, due, puzzles, lesson }: TaskInput): Task[] {
  const list: Task[] = []
  if (due > 0 || today.cards > 0)
    list.push(task('cards', '/mistakes', 'Повторить ошибки', '~5 мин', today.cards, Math.min(5, today.cards + due)))
  list.push(task('puzzles', puzzles.to, puzzles.text, '~10 мин', today.puzzles, 5))
  if (lesson)
    list.push(task('lesson', `/lessons/${lesson.slug}`, `Следующий урок: ${lesson.title}`, '~10 мин', today.lesson_positions > 0 ? 1 : 0, 1))
  list.push(task('game', '/play', 'Сыграть партию', '~15 мин', today.games > 0 ? 1 : 0, 1))
  return list
}

export const isDone = (t: Task) => t.done >= t.target

/** The swap of one local date: which task kind was replaced. */
export type Swap = { date: string; kind: TaskKind }

/**
 * The first three candidates are the tasks, the fourth is the spare. A swap of today puts the spare in place.
 * A done task never leaves the three: a done spare takes the place of the last task that is not done
 * (the counts change during the day, for example a new due card adds the cards task first).
 */
export function dailyTasks(list: Task[], swap: Swap | null, date: string): { tasks: Task[]; spare: Task | null; swapped: boolean } {
  const tasks = list.slice(0, 3)
  let spare = list[3] ?? null
  const swapped = !!swap && swap.date === date
  const i = swapped ? tasks.findIndex((t) => t.kind === swap.kind) : -1
  if (i >= 0 && spare) [tasks[i], spare] = [spare, tasks[i]]
  const j = tasks.findLastIndex((t) => !isDone(t))
  if (spare && isDone(spare) && j >= 0) [tasks[j], spare] = [spare, tasks[j]]
  // One swap a day: after it there is no spare.
  return { tasks, spare: swapped ? null : spare, swapped }
}

/** «Заменить» is shown for a task that is not done, when a spare exists and no swap was made today. */
export const canSwap = (t: Task, spare: Task | null, swapped: boolean) => !!spare && !swapped && !isDone(t)

const KEY = 'today.swap'
/** The swap stored on this device for the current login; a swap of another day is cleared. */
export function loadSwap(date: string): Swap | null {
  try {
    const s = JSON.parse(localStorage.getItem(sessionKey(KEY)) ?? 'null') as Swap | null
    if (s && s.date === date) return s
    localStorage.removeItem(sessionKey(KEY))
  } catch {
    /* no swap */
  }
  return null
}

const SHOWN = 'today.doneShown'
/** The task kinds that this page already showed done on `date`, for the current login. */
export function loadShown(date: string): TaskKind[] {
  try {
    const s = JSON.parse(localStorage.getItem(sessionKey(SHOWN)) ?? 'null') as { date: string; kinds: TaskKind[] } | null
    if (s && s.date === date) return s.kinds
  } catch {
    /* none shown */
  }
  return []
}
export function storeShown(date: string, kinds: TaskKind[]) {
  try {
    localStorage.setItem(sessionKey(SHOWN), JSON.stringify({ date, kinds }))
  } catch {
    /* the check mark can animate again after reload */
  }
}
export function storeSwap(s: Swap) {
  try {
    localStorage.setItem(sessionKey(KEY), JSON.stringify(s))
  } catch {
    /* the swap lasts until reload */
  }
}
