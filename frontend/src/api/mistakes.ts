import { signalled, tz } from './activity'
import { call } from './http'

export interface MistakeCard {
  id: number
  fen: string
  side: 'white' | 'black'
  source: 'puzzle' | 'game' | 'play'
  motif: string | null
  classification: string
  /** The move made in the game; null for puzzle cards and old cards. */
  played_san: string | null
}
export interface MistakeAnswer {
  correct: boolean
  best_uci: string
  best_san: string
  streak: number
  left: number
  learned: boolean
  due_at: string
  explanation: { text: string; source: string; model: string | null } | null
}
export interface MistakeStats {
  total: number
  due: number
  learned: number
}

export interface NextMistake {
  card: MistakeCard | null
  due: number
  /** Cards answered today and the daily limit; no card when reviewed >= limit. */
  today: { reviewed: number; limit: number }
}

export const getNextMistake = () => call<NextMistake>(`/api/mistakes/next?tz=${tz()}`)
export const getMistakeStats = () => call<MistakeStats>('/api/mistakes/stats')
export const answerMistake = signalled((id: number, uci: string) => call<MistakeAnswer>(`/api/mistakes/${id}/answer`, { uci }))
export const addPlayMistake = (card: { fen: string; best_uci: string; played_uci: string; classification: string; motif?: string }) =>
  call<{ id: number; created: boolean }>('/api/mistakes', { source: 'play', ...card })
