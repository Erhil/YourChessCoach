export type Quality = 'book' | 'best' | 'good' | 'inaccuracy' | 'mistake' | 'blunder'

/** Badge of a move: the symbol on the round mark and the Russian word (label and tooltip). */
export const QUALITY: Record<Quality, { symbol: string; word: string }> = {
  book: { symbol: 'Т', word: 'Дебютный ход' },
  best: { symbol: '★', word: 'Лучший ход' },
  good: { symbol: '✓', word: 'Хороший ход' },
  inaccuracy: { symbol: '?!', word: 'Неточность' },
  mistake: { symbol: '?', word: 'Ошибка' },
  blunder: { symbol: '??', word: 'Зевок' },
}

/** A book move shows the book badge instead of the engine class. */
export function qualityOf(classification: string | undefined, book: boolean): Quality | undefined {
  if (book) return 'book'
  return classification && classification !== 'book' && classification in QUALITY ? (classification as Quality) : undefined
}

/**
 * The badge for the board: the player's latest move, on its destination square.
 * It goes away when a later move touches that square (the piece was taken or has left).
 */
export function boardBadge(
  quality: (Quality | undefined)[],
  uci: string[],
  color: 'white' | 'black',
): { square: string; quality: Quality } | null {
  const own = color === 'white' ? 0 : 1
  let ply = uci.length - 1
  if (ply % 2 !== own) ply--
  const q = quality[ply]
  if (ply < 0 || !q) return null
  const square = uci[ply].slice(2, 4)
  const touched = uci.slice(ply + 1).some((m) => m.slice(0, 2) === square || m.slice(2, 4) === square)
  return touched ? null : { square, quality: q }
}
