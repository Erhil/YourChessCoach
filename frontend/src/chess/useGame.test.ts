import { describe, expect, it } from 'vitest'
import { countBlunders, type Game } from './useGame'

const game = (color: Game['color'], sans: string[]): Game => ({ id: 7, color, level: 1100, sans })
// Fool's mate: 1. f3 e5 2. g4 Qh4#
const fool = ['f3', 'e5', 'g4', 'Qh4#']

describe('countBlunders', () => {
  it('counts the blunders when every player move has a verdict', () => {
    expect(countBlunders(game('white', fool), { '7:0': 'good', '7:2': 'blunder' }, 'checkmate')).toBe(1)
    expect(countBlunders(game('white', fool.slice(0, 3)), { '7:0': 'good', '7:2': 'good' }, 'abandoned')).toBe(0)
  })
  it('is unknown when one player move has no verdict', () => {
    expect(countBlunders(game('white', fool), { '7:2': 'blunder' }, 'checkmate')).toBeUndefined()
    expect(countBlunders(game('white', fool.slice(0, 3)), {}, 'resign')).toBeUndefined()
  })
  it('ignores verdicts of another game', () => {
    expect(countBlunders(game('black', fool), { '6:1': 'good', '6:3': 'good' }, 'checkmate')).toBeUndefined()
  })
  it('takes the player checkmate as not a blunder when its verdict is missing', () => {
    expect(countBlunders(game('black', fool), { '7:1': 'blunder' }, 'checkmate')).toBe(1)
  })
  it('never counts the player checkmate as a blunder', () => {
    expect(countBlunders(game('black', fool), { '7:1': 'good', '7:3': 'blunder' }, 'checkmate')).toBe(0)
  })
  it('needs the verdict of a last player move that is not a checkmate', () => {
    expect(countBlunders(game('black', fool), { '7:1': 'good' }, 'abandoned')).toBeUndefined()
  })
  it('is 0 for a game without player moves', () => {
    expect(countBlunders(game('black', ['e4']), {}, 'abandoned')).toBe(0)
  })
})
