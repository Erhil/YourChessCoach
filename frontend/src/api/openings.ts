import { call } from './http'

export interface OpeningInfo {
  eco: string
  name: string
  exact: boolean
}
export interface PuzzleOpening {
  key: string
  name: string
}

/** The longest known opening along the moves (UCI from the start position), or null. */
export const openingName = (moves: string[]) => call<OpeningInfo | null>('/api/openings/name', { moves })
export const getPuzzleOpenings = () => call<PuzzleOpening[]>('/api/puzzles/openings')

export interface OpeningCardData {
  eco: string
  name: string
  line_san: string[]
  continuations: { san: string; uci: string; eco: string; name: string }[]
  lesson: { slug: string; title: string } | null
  puzzles: string | null
}
export const openingCard = (moves: string[]) =>
  call<OpeningCardData>(`/api/openings/card?moves=${encodeURIComponent(moves.join(' '))}`)
