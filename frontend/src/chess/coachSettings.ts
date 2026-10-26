const KEY = 'coach.helpLevel'
const OLD_WARN_KEY = 'coach.warnBlunder'

export type HelpLevel = 1 | 2 | 3 | 4 | 5

export const HELP_LEVELS: { value: HelpLevel; label: string }[] = [
  { value: 1, label: '1. Без подсказок' },
  { value: 2, label: '2. Только зевки' },
  { value: 3, label: '3. Ошибки и зевки' },
  { value: 4, label: '4. Предупреждать о зевке до хода' },
  { value: 5, label: '5. Разбор каждого хода' },
]

/** Help level; default 3. The old «warn before a blunder» switch, if it was on, means level 4. */
export function readHelp(): HelpLevel {
  try {
    const v = Number(localStorage.getItem(KEY))
    if (v >= 1 && v <= 5 && Number.isInteger(v)) return v as HelpLevel
    return localStorage.getItem(OLD_WARN_KEY) === '1' ? 4 : 3
  } catch {
    return 3
  }
}

export function writeHelp(level: HelpLevel) {
  try {
    localStorage.setItem(KEY, String(level))
  } catch {
    /* the choice is not kept */
  }
}

const ICONS_KEY = 'coach.moveIcons'

/** Move-quality badges; default on. Independent of the help level. */
export function readIcons(): boolean {
  try {
    return localStorage.getItem(ICONS_KEY) !== '0'
  } catch {
    return true
  }
}

export function writeIcons(on: boolean) {
  try {
    localStorage.setItem(ICONS_KEY, on ? '1' : '0')
  } catch {
    /* the choice is not kept */
  }
}
