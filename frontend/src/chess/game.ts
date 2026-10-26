import type { Chess } from 'chess.js'

export type Result = '1-0' | '0-1' | '1/2-1/2'
export type Termination = 'checkmate' | 'stalemate' | 'threefold' | 'fifty_moves' | 'insufficient' | 'resign'
export type GameStatus = { over: false } | { over: true; result: Result; termination: Termination }

/** Status of the game after the last move. Needs the Chess object with history (for threefold). */
export function gameStatus(chess: Chess): GameStatus {
  const draw = (termination: Termination): GameStatus => ({ over: true, result: '1/2-1/2', termination })
  if (chess.isCheckmate()) {
    // The side to move is mated, so the other side won.
    return { over: true, result: chess.turn() === 'w' ? '0-1' : '1-0', termination: 'checkmate' }
  }
  if (chess.isStalemate()) return draw('stalemate')
  if (chess.isInsufficientMaterial()) return draw('insufficient')
  if (chess.isThreefoldRepetition()) return draw('threefold')
  if (chess.isDrawByFiftyMoves()) return draw('fifty_moves')
  return { over: false }
}

export function statusText(status: GameStatus): string {
  if (!status.over) return ''
  switch (status.termination) {
    case 'checkmate':
      return `Мат. Победили ${status.result === '1-0' ? 'белые' : 'чёрные'}`
    case 'stalemate':
      return 'Пат — ничья'
    case 'threefold':
      return 'Троекратное повторение — ничья'
    case 'fifty_moves':
      return 'Правило 50 ходов — ничья'
    case 'resign':
      return 'Вы сдались. Партия записана как поражение'
    case 'insufficient':
      return 'Недостаточно материала — ничья'
  }
}
