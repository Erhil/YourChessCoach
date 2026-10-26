import { useEffect, useState } from 'react'
import { openingName } from '../api/openings'
import { OpeningCard } from './OpeningCard'
import css from './OpeningName.module.css'

/** The opening of the game so far. `moves` are UCI from the start position; keep the array stable between moves. */
export function OpeningName({ moves }: { moves: string[] }) {
  const [shown, setShown] = useState<{ n: number; text: string } | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (moves.length === 0) return
    let stale = false
    openingName(moves).then(
      (r) => !stale && setShown({ n: moves.length, text: r ? `${r.name} (${r.eco})` : '' }),
      () => {},
    )
    return () => {
      stale = true
    }
  }, [moves])
  if (!shown || shown.n !== moves.length || !shown.text) return null
  return (
    <>
      <button type="button" className={css.link} data-testid="opening-name" onClick={() => setOpen(true)}>
        Дебют: {shown.text}
      </button>
      {open && <OpeningCard moves={moves} onClose={() => setOpen(false)} />}
    </>
  )
}
