import { Chess } from 'chess.js'
import { describe, expect, it } from 'vitest'
import { gameStatus, statusText } from './game'

const play = (sans: string[], fen?: string) => {
  const c = fen ? new Chess(fen) : new Chess()
  sans.forEach((s) => c.move(s))
  return c
}

describe('gameStatus', () => {
  it('is ongoing at start', () => {
    expect(gameStatus(new Chess())).toEqual({ over: false })
    expect(statusText({ over: false })).toBe('')
  })
  it('detects fool\'s mate as a black win', () => {
    const s = gameStatus(play(['f3', 'e5', 'g4', 'Qh4#']))
    expect(s).toEqual({ over: true, result: '0-1', termination: 'checkmate' })
    expect(statusText(s)).toBe('Мат. Победили чёрные')
  })
  it('detects scholar\'s mate as a white win', () => {
    const s = gameStatus(play(['e4', 'e5', 'Bc4', 'Nc6', 'Qh5', 'Nf6', 'Qxf7#']))
    expect(s).toMatchObject({ result: '1-0', termination: 'checkmate' })
    expect(statusText(s)).toBe('Мат. Победили белые')
  })
  it('detects stalemate', () => {
    const s = gameStatus(new Chess('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1'))
    expect(s).toEqual({ over: true, result: '1/2-1/2', termination: 'stalemate' })
    expect(statusText(s)).toBe('Пат — ничья')
  })
  it('detects threefold repetition', () => {
    const s = gameStatus(play(['Nf3', 'Nf6', 'Ng1', 'Ng8', 'Nf3', 'Nf6', 'Ng1', 'Ng8']))
    expect(s).toMatchObject({ termination: 'threefold' })
    expect(statusText(s)).toBe('Троекратное повторение — ничья')
  })
  it('does not report threefold after two repetitions', () => {
    expect(gameStatus(play(['Nf3', 'Nf6', 'Ng1', 'Ng8'])).over).toBe(false)
  })
  it('detects the fifty-move rule', () => {
    const s = gameStatus(new Chess('4k3/8/8/8/8/8/4P3/4K2R w - - 100 80'))
    expect(s).toMatchObject({ result: '1/2-1/2', termination: 'fifty_moves' })
    expect(statusText(s)).toBe('Правило 50 ходов — ничья')
    expect(gameStatus(new Chess('4k3/8/8/8/8/8/4P3/4K2R w - - 99 80')).over).toBe(false)
  })
  it('detects insufficient material', () => {
    const s = gameStatus(new Chess('4k3/8/8/8/8/8/8/4KB2 w - - 0 1'))
    expect(s).toMatchObject({ termination: 'insufficient' })
    expect(statusText(s)).toBe('Недостаточно материала — ничья')
  })
})
