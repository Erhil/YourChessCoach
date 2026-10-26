import { call } from './http'

export interface BenchPair {
  item_id: string
  fen: string
  move_san: string
  classification: 'best' | 'good' | 'inaccuracy' | 'mistake' | 'blunder'
  best_move_san: string | null
  a: { text: string }
  b: { text: string }
  token: string
}
export interface BenchModel {
  model: string
  votes: number
  wins: number
  losses: number
  ties: number
  win_rate: number
  valid_pct: number
  mean_seconds: number
  vram_gb: number | null
}
export interface BenchResults {
  models: BenchModel[]
  default_model: string
  bench_created: string
}

export const getPair = () => call<BenchPair>('/api/admin/bench/pair')
export const vote = (token: string, winner: 'a' | 'b' | 'tie') =>
  call<{ votes: number }>('/api/admin/bench/vote', { token, winner })
export const getResults = () => call<BenchResults>('/api/admin/bench/results')
export const setDefaultModel = (model: string) => call<{ default_model: string }>('/api/admin/bench/default', { model })
