import { useEffect, useMemo, useRef, useState } from 'react'
import { openingName } from '../api/openings'
import { qualityOf, type Quality } from './quality'

/**
 * Quality of every ply of the game (undefined for the opponent's plies and for unknown ones).
 * `verdicts` holds the engine class by `${game id}:${ply}`. A book move is a position that is an
 * exact entry of the openings reference. Nothing is asked when `enabled` is false.
 */
export function useQuality(
  gid: number | undefined,
  color: 'white' | 'black',
  uci: string[],
  verdicts: Record<string, string>,
  enabled: boolean,
): (Quality | undefined)[] {
  const [book, setBook] = useState<Record<string, boolean>>({})
  const asked = useRef(new Set<string>())
  const first = color === 'black' ? 1 : 0

  useEffect(() => {
    if (!enabled) return
    for (let ply = first; ply < uci.length; ply += 2) {
      const key = uci.slice(0, ply + 1).join(' ')
      if (asked.current.has(key)) continue
      asked.current.add(key)
      openingName(uci.slice(0, ply + 1)).then(
        (r) => setBook((p) => ({ ...p, [key]: !!r?.exact })),
        () => asked.current.delete(key),
      )
    }
  }, [enabled, first, uci])

  return useMemo(
    () =>
      uci.map((_, ply) =>
        enabled && ply % 2 === first
          ? qualityOf(verdicts[`${gid}:${ply}`], !!book[uci.slice(0, ply + 1).join(' ')])
          : undefined,
      ),
    [enabled, first, gid, uci, verdicts, book],
  )
}
