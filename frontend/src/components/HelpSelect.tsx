import { useState } from 'react'
import { HELP_LEVELS, readHelp, writeHelp, type HelpLevel } from '../chess/coachSettings'

/** The «Помощь тренера» choice; kept in localStorage. */
export function HelpSelect({ onChange }: { onChange?: (level: HelpLevel) => void }) {
  const [level, setLevel] = useState(readHelp)
  return (
    <label className="choice">
      Помощь тренера
      <select
        value={level}
        onChange={(e) => {
          const v = Number(e.target.value) as HelpLevel
          writeHelp(v)
          setLevel(v)
          onChange?.(v)
        }}
      >
        {HELP_LEVELS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}
