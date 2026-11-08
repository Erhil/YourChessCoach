import { call } from './http.ts'

export type TrainingKind = 'practice' | 'delayed'
type TrainingAction = 'move' | 'hint' | 'reveal' | 'next' | 'finish'
export type TrainingIntent =
  | { kind: TrainingKind }
  | { session: number; version: number; action: TrainingAction; uci?: string }
export type TrainingWrite = TrainingIntent & { client_id: string; expected_login: string }

export interface TrainingSession {
  id: number
  version: number
  kind: TrainingKind
  total: number
  step: number
  state: 'question' | 'feedback' | 'done'
  position: {
    fen: string
    side: 'white' | 'black'
    source: 'game' | 'exercise'
    novelty: 'personal' | 'new'
    rating: number | null
    hint?: string | null
  } | null
  feedback: {
    correct: boolean | null
    text: string
    line: string[]
    played_uci?: string | null
    original_uci?: string | null
    original_text?: string | null
  } | null
  counts: {
    assigned: number
    independent: { answered: number; correct: number }
    assisted: { answered: number; correct: number }
    unfinished: number
  }
  delay_days: number | null
  difficulty: { min: number; max: number } | null
  notice?: string | null
  new_positions: number
}

export interface TrainingStatus {
  session: TrainingSession | null
  delayed_available: boolean
  delayed_notice?: string | null
}

export const getTraining = (login: string) =>
  call<TrainingStatus>(`/api/training?${new URLSearchParams({ expected_login: login })}`)

export const writeTraining = (write: TrainingWrite) => {
  if ('session' in write) {
    const { session, ...body } = write
    return call<TrainingSession>(`/api/training/${session}/action`, body)
  }
  return call<TrainingSession>('/api/training/start', write)
}
