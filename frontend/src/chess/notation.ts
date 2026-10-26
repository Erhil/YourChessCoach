const FIGURES: Record<string, string> = { K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘' }

/** Converts SAN to figurine notation: Nf3 -> ♘f3, e8=Q+ -> e8=♕+. Castling is unchanged. */
export function toFigurine(san: string): string {
  return san
    .replace(/^[KQRBN]/, (p) => FIGURES[p])
    .replace(/=([QRBN])/, (_, p: string) => `=${FIGURES[p]}`)
}

/** Splits a UCI move: e7e8q -> { from: 'e7', to: 'e8', promotion: 'q' }. */
export const splitUci = (uci: string) => ({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] })

/** The reverse of `splitUci`: a move object (from, to, optional promotion) as a UCI string. */
export const toUci = (m: { from: string; to: string; promotion?: string }) => m.from + m.to + (m.promotion ?? '')

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export const CLASS_WORD: Record<string, string> = {
  blunder: 'зевок',
  mistake: 'ошибка',
  inaccuracy: 'неточность',
  good: 'хороший ход',
  best: 'отличный ход',
}
