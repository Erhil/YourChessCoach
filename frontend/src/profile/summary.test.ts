import { describe, expect, it } from 'vitest'
import type { WeekSummary } from '../api/progress'
import { blunderTrend, comma, deckLeft, lastEarned, ratingChange, signed, topThemes } from './summary'

const now = new Date('2026-10-25T12:00:00Z')
const pt = (at: string, rating: number) => ({ at, rating })
const week = (start: string, b: number | null): WeekSummary => ({
  start, active_days: 1, puzzles_solved: 0, rating_change: 0, player_moves: b === null ? 0 : 10, blunders_per_10_moves: b,
})
const theme = (key: string, rating: number, attempts = 3) => ({ key, name: key, rating, attempts })

describe('format', () => {
  it('uses a comma and a real minus', () => {
    expect(comma(1.25, 2)).toBe('1,25')
    expect(signed(12)).toBe('+12')
    expect(signed(-0.4, 1)).toBe('−0,4')
    expect(signed(0)).toBe('0')
  })
})

describe('ratingChange', () => {
  it('counts from the last rating before the 7 days', () => {
    const history = [pt('2026-10-10T10:00:00Z', 620), pt('2026-10-17T10:00:00Z', 640), pt('2026-10-24T10:00:00Z', 655)]
    expect(ratingChange({ rating: 655, attempts: 3, solved: 3, history }, now)).toEqual({ value: 15, since: 'за 7 дней' })
  })
  it('counts from the start rating since the first attempt when it is inside the 7 days', () => {
    const p = { rating: 612, attempts: 1, solved: 1, history: [pt('2026-10-25T10:00:00Z', 612)] }
    expect(ratingChange(p, now)).toEqual({ value: 12, since: 'с первой задачи' })
  })
  it('counts from the first point and names its date when the history is cut', () => {
    const history = [pt('2026-10-24T10:00:00Z', 700), pt('2026-10-25T10:00:00Z', 690)]
    expect(ratingChange({ rating: 690, attempts: 500, solved: 1, history }, now)).toEqual({ value: -10, since: 'с 24.10' })
  })
  it('is 0 without attempts', () => {
    expect(ratingChange({ rating: 600, attempts: 0, solved: 0, history: [] }, now)).toEqual({ value: 0, since: 'за 7 дней' })
  })
})

describe('blunderTrend', () => {
  it('compares the latest week with a value to the week before it with a value', () => {
    const t = blunderTrend([week('2026-10-06', 1.5), week('2026-10-13', null), week('2026-10-20', 1.1)])!
    expect(t.value).toBe(1.1)
    expect(t.change).toBe(-0.4)
    expect(t.than).toBe('в неделю с 06.10')
    expect(t.known).toHaveLength(2)
    expect(blunderTrend([week('2026-10-13', 1.5), week('2026-10-20', 1.8)])!.than).toBe('неделей раньше')
  })
  it('has no change for one week and no trend without games', () => {
    expect(blunderTrend([week('2026-10-20', 2)])!.change).toBeNull()
    expect(blunderTrend([week('2026-10-20', null)])).toBeNull()
  })
})

describe('topThemes', () => {
  it('takes up to 4 themes with 3 attempts or more, the highest rating first', () => {
    const r = topThemes([theme('a', 500), theme('b', 700), theme('c', 650), theme('d', 550), theme('e', 900, 2), theme('f', 600)])
    expect(r.items.map((t) => t.key)).toEqual(['b', 'c', 'f', 'd'])
    expect(r.early).toBe(false)
  })
  it('uses all themes when none has 3 attempts', () => {
    const r = topThemes([theme('a', 590, 1), theme('b', 610, 2)])
    expect(r.items.map((t) => t.key)).toEqual(['b', 'a'])
    expect(r.early).toBe(true)
  })
})

describe('deck and achievements', () => {
  it('limits the deck by the daily limit', () => {
    expect(deckLeft({ card: null, due: 14, today: { reviewed: 3, limit: 10 } })).toBe(7)
    expect(deckLeft({ card: null, due: 2, today: { reviewed: 0, limit: 10 } })).toBe(2)
    expect(deckLeft({ card: null, due: 5, today: { reviewed: 12, limit: 10 } })).toBe(0)
  })
  it('finds the achievement earned last', () => {
    const a = (key: string, earned_at: string) => ({ key, title: key, text: '', earned_at })
    expect(lastEarned([a('x', '2026-10-20T10:00:00Z'), a('y', '2026-10-24T10:00:00Z'), a('z', '2026-10-01T10:00:00Z')])!.key).toBe('y')
    expect(lastEarned([])).toBeNull()
  })
})
