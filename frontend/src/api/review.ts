import { call } from './http'

export interface GameRow {
  id: number
  created_at: string
  player_color: 'white' | 'black'
  level: number | null
  result: string
  termination: string | null
  moves_count: number
  takebacks: number
  hints: number
  training: boolean
}
export interface ReviewMove {
  ply: number
  san: string
  uci: string
  color: 'white' | 'black'
  fen_before: string
  classification: string
}
export interface KeyMoment {
  ply: number
  san: string
  classification: string
  facts: {
    fen_before: string
    best_move: { san: string; uci: string } | null
    player_move: { san: string; uci: string }
    best_line: string[]
    lesson: { slug: string; title: string } | null
  }
  explanation: { text: string; source: string }
}
export interface ReviewResult {
  side: 'white' | 'black'
  moves: ReviewMove[]
  key_moments: KeyMoment[]
  summary: { inaccuracy: number; mistake: number; blunder: number }
}

export const getGames = () => call<GameRow[]>('/api/games')

export const reviewGame = (body: { pgn: string; side: 'white' | 'black' } | { game_id: number }) =>
  call<ReviewResult>('/api/review', body)
