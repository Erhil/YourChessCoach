import { describe, expect, it } from 'vitest'
import { nextLesson } from './nextLesson'

const l = (number: number, prerequisites: string[] = [], completed = false) => ({
  slug: `l${number}`,
  number,
  prerequisites,
  completed,
})

describe('nextLesson', () => {
  it('returns the first lesson when nothing is done', () => {
    expect(nextLesson([l(2), l(1)])?.slug).toBe('l1')
  })
  it('skips completed lessons', () => {
    expect(nextLesson([l(1, [], true), l(2)])?.slug).toBe('l2')
  })
  it('skips lessons with unfinished prerequisites', () => {
    expect(nextLesson([l(1), l(2, ['l3']), l(3, ['l1'])])?.slug).toBe('l1')
    expect(nextLesson([l(1, [], true), l(2, ['l3']), l(3, ['l1'])])?.slug).toBe('l3')
  })
  it('treats a missing completed flag as not completed', () => {
    expect(nextLesson([{ slug: 'a', number: 1, prerequisites: [] }])?.slug).toBe('a')
  })
  it('returns null when all are completed', () => {
    expect(nextLesson([l(1, [], true)])).toBeNull()
  })
})
