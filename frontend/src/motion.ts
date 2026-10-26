const KEY = 'awards.animation'

/** The «Анимация наград» switch on this device; default on. */
export function readAnim(): boolean {
  try {
    return localStorage.getItem(KEY) !== '0'
  } catch {
    return true
  }
}

export function writeAnim(on: boolean) {
  try {
    localStorage.setItem(KEY, on ? '1' : '0')
  } catch {
    /* the choice is not kept */
  }
}

/** The class of the award animation, or none when the switch is off. */
export const popClass = () => (readAnim() ? 'pop' : '')
