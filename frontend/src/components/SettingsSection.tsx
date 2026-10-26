import { useEffect, useState } from 'react'
import { getHealth, type Health } from '../api/client.ts'
import { getTheme, setTheme, type Theme } from '../theme.ts'
import { AnimToggle } from './AnimToggle.tsx'
import { HelpSelect } from './HelpSelect.tsx'
import { IconsToggle } from './IconsToggle.tsx'
import { McpKey } from './McpKey.tsx'

const options: { value: Theme; label: string }[] = [
  { value: 'system', label: 'Системная' },
  { value: 'light', label: 'Светлая' },
  { value: 'dark', label: 'Тёмная' },
]

/** «Настройки» of the profile: theme, coach help, move icons, award animation, MCP key, server line. */
export default function SettingsSection() {
  const [theme, setThemeState] = useState<Theme>(getTheme)
  // undefined = loading, null = no connection
  const [health, setHealth] = useState<Health | null | undefined>(undefined)
  useEffect(() => {
    getHealth().then(setHealth, () => setHealth(null))
  }, [])
  return (
    <section id="settings" aria-label="Настройки">
      <h2>Настройки</h2>
      <fieldset style={{ border: 0, padding: 0 }}>
        <legend>Тема</legend>
        {options.map((o) => (
          <label key={o.value} className="choice">
            <input
              type="radio"
              name="theme"
              checked={theme === o.value}
              onChange={() => {
                setTheme(o.value)
                setThemeState(o.value)
              }}
            />
            {o.label}
          </label>
        ))}
      </fieldset>
      <HelpSelect />
      <IconsToggle />
      <AnimToggle />
      <McpKey />
      {health !== undefined && (
        <p className="muted">
          {health ? 'Сервер: работает' : 'Сервер: нет связи'}
          {'. '}Stockfish: {health?.engines?.stockfish.available ? 'найден' : 'не найден'}
        </p>
      )}
    </section>
  )
}
