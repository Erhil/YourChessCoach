import { signalled } from './activity'
import { call } from './http'

export interface Health {
  status: string
  backup?: { error: string | null }
  version: string
  /** Only with a user session; without one the server sends status and version alone. */
  engines?: { stockfish: { available: boolean } }
  llm?: { enabled: boolean; available: boolean; model?: string; status?: string; reachable?: boolean; model_present?: boolean }
}

export const getHealth = () => call<Health>('/api/health')

export interface OpponentLevel {
  level: number
  label: string
  engine: string
}
export interface OpponentMove {
  uci: string
  san: string
  engine: string
}
export interface EvalLine {
  rank: number
  score: { cp: number | null; mate: number | null }
  pv_san: string[]
  pv_uci: string[]
}
export interface Analysis {
  fen: string
  turn: string
  depth: number
  lines: EvalLine[]
}
export interface GameError {
  ply: number
  best_uci: string
  best_line?: string[]
  classification: 'mistake' | 'blunder'
  motif?: string
}
export interface GameRecord {
  expected_login?: string
  client_id?: string
  pgn: string
  player_color: 'white' | 'black'
  level: number
  result: string
  termination: string
  /** Player moves that the coach classified as a blunder. */
  blunders?: number
  /** A game with a takeback or a hint is a training game: it does not count in wins. */
  takebacks?: number
  hints?: number
  errors?: GameError[]
}

export const getOpponentLevels = () => call<OpponentLevel[]>('/api/opponent/levels')

export const getOpponentMove = (moves: string[], level: number) =>
  call<OpponentMove>('/api/opponent/move', { moves, level })

export const analyze = (fen: string, movetime_ms = 300, multipv?: number) =>
  call<Analysis>('/api/analyze', { fen, movetime_ms, multipv })

export const saveGame = signalled((game: GameRecord) => call<{ id: number }>('/api/games', game))

export interface PuzzleTheme {
  key: string
  name: string
  count: number
}
export interface Puzzle {
  id: string
  fen: string
  opponent_move: string
  solution: string[]
  rating: number
  themes: { key: string; name: string }[]
  player_color: 'white' | 'black'
  user_rating: number
}
export interface AttemptResult {
  rating_before: number
  rating_after: number
  delta: number
}
export interface AttemptDetails {
  /** One-based learner turn, starting after the puzzle's first opponent move. */
  ply: number
  played_uci: string | null
  first_uci: string | null
  revealed: boolean
  elapsed_ms: number
}

export const getPuzzleThemes = () => call<PuzzleTheme[]>('/api/puzzles/themes')
export const getNextPuzzle = (theme: string, opening = '', exclude = '') => {
  const q = new URLSearchParams()
  if (exclude) q.set('exclude', exclude)
  if (theme) q.set('theme', theme)
  if (opening) q.set('opening', opening)
  return call<Puzzle>(`/api/puzzles/next${q.size ? `?${q}` : ''}`)
}
export const getPuzzleRating = () => call<{ overall: number }>('/api/puzzles/rating')
export const sendAttempt = signalled((id: string, solved: boolean, used_hint: boolean, client_id?: string, details?: AttemptDetails, expected_login?: string) =>
  call<AttemptResult>(`/api/puzzles/${id}/attempt`, { solved, used_hint, client_id, details, expected_login }),
)
export interface CoachResult {
  facts: {
    classification: 'best' | 'good' | 'inaccuracy' | 'mistake' | 'blunder'
    lesson: { slug: string; title: string } | null
    best_move?: { san: string; uci: string } | null
    best_line?: string[]
    refutation?: string[]
    motifs_against?: { kind: string }[]
    motifs_missed?: { kind: string }[]
  }
  explanation: { text: string; source: string } | null
}
export const coachMove = (fen: string, move: string, help_level?: number) => call<CoachResult>('/api/coach/move', { fen, move, help_level })

export interface LessonSummary {
  slug: string
  number: number
  title: string
  level: number
  themes: string[]
  prerequisites: string[]
  section?: string | null
  openings?: string[]
  positions: number
  solved?: number
  completed?: boolean
}
export type LessonSegment =
  | { type: 'markdown'; text: string }
  | { type: 'chess'; fen: string; task: string; solution: string[]; hint: string }
  | { type: 'line'; title: string; fen: string; side: 'white' | 'black'; moves: { san: string; text: string }[] }
export interface Lesson extends Omit<LessonSummary, 'solved'> {
  segments: LessonSegment[]
  solved: number[]
}

export const getLessons = () => call<LessonSummary[]>('/api/lessons')
export const getLesson = (slug: string) => call<Lesson>(`/api/lessons/${encodeURIComponent(slug)}`)
export const sendLessonPosition = signalled((slug: string, index: number) =>
  call<{ solved: number[]; positions: number; completed: boolean }>(
    `/api/lessons/${encodeURIComponent(slug)}/positions/${index}`,
    {},
  ),
)
export const askLesson = (slug: string, question: string, position: number | null) =>
  call<{ answer: string | null; source: 'llm' | null; reason: string | null }>(
    `/api/lessons/${encodeURIComponent(slug)}/ask`,
    position === null ? { question } : { question, position },
  )

export type CoachQuestion = 'why' | 'threat' | 'better' | 'free'
export interface CoachAnswer {
  answer: string | null
  /** Moves (SAN) to draw as arrows and the position they start from. */
  line: { fen: string; moves: string[] } | null
  reason: string | null
}
export const askAboutMove = (fen: string, move: string, question: CoachQuestion, text?: string) =>
  call<CoachAnswer>('/api/coach/ask', text === undefined ? { fen, move, question } : { fen, move, question, text })

export interface Hint {
  /** `wins`: what the threat takes, in the accusative («коня»); `mate`: the threat is a mate. */
  threat: { san: string; uci: string; wins?: string | null; mate?: boolean } | null
  best: { uci: string; piece: string }
}
export const coachHint = (fen: string) => call<Hint>('/api/coach/hint', { fen })
