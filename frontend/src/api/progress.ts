import { tz } from './activity'
import { call } from './http'

export interface WeekSummary {
  /** The Monday, YYYY-MM-DD. */
  start: string
  active_days: number
  puzzles_solved: number
  rating_change: number
  player_moves: number
  blunders_per_10_moves: number | null
}

export interface Progress {
  puzzles: { rating: number; attempts: number; solved: number; history: { at: string; rating: number }[] }
  themes: { key: string; name: string; rating: number; attempts: number }[]
  weak_theme: { key: string; name: string } | null
  games: {
    count: number
    wins: number
    losses: number
    draws: number
    player_moves: number
    blunders: number
    blunders_per_10_moves: number
    /** Training games (with a takeback or a hint); not in wins, losses and draws. */
    training?: number
  }
  lessons: { completed: number; total: number }
  mistakes: { total: number; due: number; learned: number }
  /** Local dates with activity in the last 12 weeks, ascending; only in the user's own progress. */
  calendar?: string[]
  /** The last 8 weeks, oldest first; only in the user's own progress. */
  weeks?: WeekSummary[]
}

export const getProgress = () => call<Progress>(`/api/progress?tz=${tz()}`)
