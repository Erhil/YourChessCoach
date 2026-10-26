import { describe, expect, it } from 'vitest'
import { boardBadge, qualityOf, type Quality } from './quality'

describe('qualityOf', () => {
  it('book wins over the engine class', () => {
    expect(qualityOf('blunder', true)).toBe('book')
  })
  it('maps engine classes and ignores unknown ones', () => {
    expect(qualityOf('inaccuracy', false)).toBe('inaccuracy')
    expect(qualityOf(undefined, false)).toBeUndefined()
    expect(qualityOf('other', false)).toBeUndefined()
  })
})

describe('boardBadge', () => {
  const q = (...a: (Quality | undefined)[]) => a
  it('shows the last own move', () => {
    expect(boardBadge(q('good'), ['e2e4'], 'white')).toEqual({ square: 'e4', quality: 'good' })
  })
  it('keeps it after a reply that does not touch the square', () => {
    expect(boardBadge(q('best'), ['e2e4', 'e7e5'], 'white')).toEqual({ square: 'e4', quality: 'best' })
  })
  it('drops it when the reply takes the piece', () => {
    expect(boardBadge(q('blunder'), ['e2e4', 'd5e4'], 'white')).toBeNull()
  })
  it('works for black', () => {
    expect(boardBadge(q(undefined, 'mistake'), ['e2e4', 'a7a5'], 'black')).toEqual({ square: 'a5', quality: 'mistake' })
  })
  it('is empty without a verdict', () => {
    expect(boardBadge([], [], 'white')).toBeNull()
  })
})
