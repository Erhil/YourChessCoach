import { describe, expect, it } from 'vitest'
import { adviceArrows, lineArrows } from './arrows'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

describe('lineArrows', () => {
  it('alternates colours and grows the step along a SAN line', () => {
    expect(lineArrows(START, ['e4', 'e5', 'Nf3'])).toEqual([
      { from: 'e2', to: 'e4', color: 'green', step: 0 },
      { from: 'e7', to: 'e5', color: 'red', step: 1 },
      { from: 'g1', to: 'f3', color: 'green', step: 2 },
    ])
  })
  it('accepts UCI moves and cuts the line to 3 arrows', () => {
    const arrows = lineArrows(START, ['e2e4', 'e7e5', 'g1f3', 'b8c6'])
    expect(arrows.map((a) => a.color)).toEqual(['green', 'red', 'green'])
    expect(arrows).toHaveLength(3)
  })
  it('handles capture and check in SAN, and black to move', () => {
    // After 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6 white plays Qxf7#.
    const fen = 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4'
    expect(lineArrows(fen, ['Qxf7#'])).toEqual([{ from: 'h5', to: 'f7', color: 'green', step: 0 }])
    const black = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
    expect(lineArrows(black, ['d5', 'exd5+'])[1]).toMatchObject({ from: 'e4', to: 'd5', color: 'red' })
  })
  it('stops at an illegal move', () => {
    expect(lineArrows(START, ['e4', 'e4'])).toHaveLength(1)
  })
})

describe('adviceArrows', () => {
  it('draws only the opponent reply in red and the better move in green', () => {
    // 1.e4 e5 2.Nf3 Nc6 3.Nxe5?: Nxe5 wins the knight; 3.Bc4 was better.
    const before = 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3'
    const arrows = adviceArrows(before, 'f3e5', { refutation: ['c6e5', 'd2d4'], best_move: { uci: 'f1c4' } })
    expect(arrows).toEqual([
      { from: 'c6', to: 'e5', color: 'red', step: 0 },
      { from: 'f1', to: 'c4', color: 'green', step: 0 },
    ])
  })
})
