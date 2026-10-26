import { describe, expect, it } from 'vitest'
import { gridDays, localIso } from './ActivityCalendar'

const weekday = (iso: string) => new Date(`${iso}T12:00:00`).getDay()

describe('gridDays', () => {
  it('starts on a Monday 11 weeks before the week of a Sunday; today is the last cell', () => {
    const now = new Date(2026, 9, 25, 15) // Sunday
    const days = gridDays(now)
    expect(days).toHaveLength(84)
    expect(days[0].iso).toBe('2026-08-03')
    expect(weekday(days[0].iso)).toBe(1)
    expect(days.at(-1)).toEqual({ iso: localIso(now), future: false })
  })

  it('on a Monday, today is the last day cell and the rest of its week is future', () => {
    const now = new Date(2026, 9, 26, 9) // Monday
    const days = gridDays(now)
    expect(days[0].iso).toBe('2026-08-10')
    expect(weekday(days[0].iso)).toBe(1)
    const past = days.filter((d) => !d.future)
    expect(past.at(-1)!.iso).toBe('2026-10-26')
    expect(past).toHaveLength(78)
    expect(days.slice(78).every((d) => d.future)).toBe(true)
  })
})
