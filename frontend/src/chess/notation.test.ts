import { describe, expect, it } from 'vitest'
import { toFigurine } from './notation'

describe('toFigurine', () => {
  it('replaces piece letters', () => {
    expect(toFigurine('Nf3')).toBe('♘f3')
    expect(toFigurine('Bxf7+')).toBe('♗xf7+')
    expect(toFigurine('Qh5#')).toBe('♕h5#')
    expect(toFigurine('Rad1')).toBe('♖ad1')
    expect(toFigurine('Kg2')).toBe('♔g2')
  })
  it('leaves pawn moves and castling unchanged', () => {
    expect(toFigurine('e4')).toBe('e4')
    expect(toFigurine('exd5')).toBe('exd5')
    expect(toFigurine('O-O')).toBe('O-O')
    expect(toFigurine('O-O-O+')).toBe('O-O-O+')
  })
  it('replaces promotion pieces', () => {
    expect(toFigurine('e8=Q')).toBe('e8=♕')
    expect(toFigurine('exd8=N+')).toBe('exd8=♘+')
  })
})
