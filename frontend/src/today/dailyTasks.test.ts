import { afterEach, describe, expect, it, vi } from 'vitest'
import { setSessionLogin } from '../auth/session'
import { canSwap, candidates, dailyTasks, loadShown, loadSwap, storeShown, storeSwap, type TaskInput } from './dailyTasks'

const zero = { puzzles: 0, cards: 0, lesson_positions: 0, games: 0 }
const input = (p: Partial<TaskInput> = {}): TaskInput => ({
  today: zero,
  due: 0,
  puzzles: { to: '/puzzles', text: 'Смешанные задачи — 5 задач' },
  lesson: { slug: 'l1', title: 'Первый урок' },
  ...p,
})
const kinds = (list: { kind: string }[]) => list.map((t) => t.kind)
const D = '2026-10-24'

describe('candidates', () => {
  it('puts cards first when cards are due', () => {
    const c = candidates(input({ due: 7 }))
    expect(kinds(c)).toEqual(['cards', 'puzzles', 'lesson', 'game'])
    expect(c[0].target).toBe(5)
  })
  it('has no cards task without due cards and without answers today', () => {
    expect(kinds(candidates(input()))).toEqual(['puzzles', 'lesson', 'game'])
  })
  it('keeps the cards task after the last due card is answered today', () => {
    expect(candidates(input({ today: { ...zero, cards: 2 } }))[0]).toMatchObject({ kind: 'cards', done: 2, target: 2 })
  })
  it('targets the answered and due cards, at most 5', () => {
    expect(candidates(input({ due: 2, today: { ...zero, cards: 1 } }))[0]).toMatchObject({ done: 1, target: 3 })
    expect(candidates(input({ due: 9, today: { ...zero, cards: 3 } }))[0]).toMatchObject({ done: 3, target: 5 })
  })
  it('skips the lesson when there is no next lesson: the game is a task', () => {
    expect(kinds(candidates(input({ lesson: null, due: 1 })))).toEqual(['cards', 'puzzles', 'game'])
  })
  it('caps done counts at the target', () => {
    const c = candidates(input({ today: { puzzles: 9, cards: 0, lesson_positions: 4, games: 3 } }))
    expect(c.map((t) => `${t.done}/${t.target}`)).toEqual(['5/5', '1/1', '1/1'])
  })
})

describe('dailyTasks and the swap', () => {
  it('takes three tasks and the fourth candidate as the spare', () => {
    const r = dailyTasks(candidates(input({ due: 1 })), null, D)
    expect(kinds(r.tasks)).toEqual(['cards', 'puzzles', 'lesson'])
    expect(r.spare?.kind).toBe('game')
  })
  it('has no spare and no swap with three candidates', () => {
    const r = dailyTasks(candidates(input()), null, D)
    expect(r.spare).toBeNull()
    expect(r.tasks.some((t) => canSwap(t, r.spare, r.swapped))).toBe(false)
  })
  it('replaces the swapped task with the spare in its place, once', () => {
    const r = dailyTasks(candidates(input({ due: 1 })), { date: D, kind: 'puzzles' }, D)
    expect(kinds(r.tasks)).toEqual(['cards', 'game', 'lesson'])
    expect(r.spare).toBeNull()
    expect(r.tasks.some((t) => canSwap(t, r.spare, r.swapped))).toBe(false)
  })
  it('ignores a swap of another day', () => {
    const r = dailyTasks(candidates(input({ due: 1 })), { date: '2026-10-23', kind: 'puzzles' }, D)
    expect(kinds(r.tasks)).toEqual(['cards', 'puzzles', 'lesson'])
    expect(canSwap(r.tasks[1], r.spare, r.swapped)).toBe(true)
  })
  it('does not offer a swap for a done task', () => {
    const r = dailyTasks(candidates(input({ due: 1, today: { ...zero, puzzles: 5 } })), null, D)
    expect(canSwap(r.tasks[1], r.spare, r.swapped)).toBe(false)
    expect(canSwap(r.tasks[2], r.spare, r.swapped)).toBe(true)
  })
  it('keeps a done game in the three when a due card adds the cards task', () => {
    // Morning: no due cards, the game is a task. The game is played and its blunder adds a due card.
    const r = dailyTasks(candidates(input({ due: 1, today: { ...zero, games: 1 } })), null, D)
    expect(kinds(r.tasks)).toEqual(['cards', 'puzzles', 'game'])
    expect(r.tasks[2].done).toBe(1)
    expect(r.spare?.kind).toBe('lesson')
    expect(r.tasks.filter((t) => canSwap(t, r.spare, r.swapped)).map((t) => t.kind)).toEqual(['cards', 'puzzles'])
  })
  it('puts a done task in place of the last task that is not done', () => {
    const r = dailyTasks(candidates(input({ due: 1, today: { ...zero, lesson_positions: 2, games: 1 } })), null, D)
    expect(kinds(r.tasks)).toEqual(['cards', 'game', 'lesson'])
    expect(r.spare?.kind).toBe('puzzles')
  })
  it('keeps a task that is done after it was swapped in or swapped out', () => {
    const swapIn = dailyTasks(candidates(input({ due: 1, today: { ...zero, games: 1 } })), { date: D, kind: 'lesson' }, D)
    expect(kinds(swapIn.tasks)).toEqual(['cards', 'puzzles', 'game'])
    // The lesson was swapped out, then done anyway: it comes back in place of the last task that is not done.
    const swapOut = dailyTasks(candidates(input({ due: 1, today: { ...zero, lesson_positions: 1 } })), { date: D, kind: 'lesson' }, D)
    expect(kinds(swapOut.tasks)).toEqual(['cards', 'puzzles', 'lesson'])
    expect(swapOut.spare).toBeNull()
  })
})

describe('swap storage', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('keeps the swap for the date and the login, and a new day clears it', () => {
    const m = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => m.get(k) ?? null,
      setItem: (k: string, v: string) => m.set(k, v),
      removeItem: (k: string) => m.delete(k),
    })
    setSessionLogin('anna')
    storeSwap({ date: D, kind: 'lesson' })
    expect(loadSwap(D)).toEqual({ date: D, kind: 'lesson' })
    setSessionLogin('boris')
    expect(loadSwap(D)).toBeNull()
    setSessionLogin('anna')
    expect(loadSwap('2026-10-25')).toBeNull()
    expect(loadSwap(D)).toBeNull()
  })
  it('keeps the shown done tasks for the date and the login', () => {
    const m = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => m.set(k, v) })
    setSessionLogin('anna')
    expect(loadShown(D)).toEqual([])
    storeShown(D, ['puzzles'])
    expect(loadShown(D)).toEqual(['puzzles'])
    expect(loadShown('2026-10-25')).toEqual([])
    setSessionLogin('boris')
    expect(loadShown(D)).toEqual([])
  })
})
