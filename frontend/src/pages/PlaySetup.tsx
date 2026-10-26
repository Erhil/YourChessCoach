import { useEffect, useState } from 'react'
import { getOpponentLevels, type OpponentLevel } from '../api/client'
import { loadPrefs, storePrefs, type Prefs } from '../chess/gameStore'
import css from './Play.module.css'

type Props = { onStart: (color: Prefs['color'], level: number) => void }

/** The card shown while there is no game: colour, level and the «Начать» button. */
export function PlaySetup({ onStart }: Props) {
  const [prefs] = useState(loadPrefs)
  const [levels, setLevels] = useState<OpponentLevel[]>([{ level: prefs.level, label: String(prefs.level), engine: '' }])
  const [level, setLevel] = useState(prefs.level)
  const [color, setColor] = useState(prefs.color)

  useEffect(() => {
    getOpponentLevels().then(setLevels, () => {})
  }, [])

  const shown = levels.some((l) => l.level === level) ? level : levels[0].level
  const go = () => {
    storePrefs({ color, level: shown })
    onStart(color, shown)
  }

  return (
    <section className={css.setup} aria-label="Новая партия">
      <h2>Новая партия</h2>
      <label className="choice">
        Цвет
        <select value={color} onChange={(e) => setColor(e.target.value as Prefs['color'])}>
          <option value="white">Белые</option>
          <option value="black">Чёрные</option>
          <option value="random">Случайно</option>
        </select>
      </label>
      <label className="choice">
        Уровень
        <select value={shown} onChange={(e) => setLevel(Number(e.target.value))}>
          {levels.map((l) => (
            <option key={l.level} value={l.level}>
              {l.label}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className={css.start} onClick={go}>
        Начать
      </button>
    </section>
  )
}
