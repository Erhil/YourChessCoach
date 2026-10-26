import { useState } from 'react'
import { readIcons, writeIcons } from '../chess/coachSettings'

/** The «Значки качества хода» switch; kept in localStorage. */
export function IconsToggle({ onChange }: { onChange?: (on: boolean) => void }) {
  const [on, setOn] = useState(readIcons)
  return (
    <label className="choice">
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => {
          writeIcons(e.target.checked)
          setOn(e.target.checked)
          onChange?.(e.target.checked)
        }}
      />
      Значки качества хода
    </label>
  )
}
