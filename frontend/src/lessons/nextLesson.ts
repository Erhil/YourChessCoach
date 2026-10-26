import type { LessonSummary } from '../api/client'

type L = Pick<LessonSummary, 'slug' | 'number' | 'prerequisites' | 'completed'>

/** The first lesson by number that is not completed and has all prerequisites completed. */
export function nextLesson<T extends L>(lessons: T[]): T | null {
  const done = new Set(lessons.filter((l) => l.completed).map((l) => l.slug))
  const open = lessons.filter((l) => !l.completed && l.prerequisites.every((p) => done.has(p)))
  return open.sort((a, b) => a.number - b.number)[0] ?? null
}
