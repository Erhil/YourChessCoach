import { useState } from 'react'
import { readAnim, writeAnim } from '../motion'

/** The «Анимация наград» switch; kept in localStorage. */
export function AnimToggle() {
  const [on, setOn] = useState(readAnim)
  return (
    <label className="choice">
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => {
          writeAnim(e.target.checked)
          setOn(e.target.checked)
        }}
      />
      Анимация наград
    </label>
  )
}
