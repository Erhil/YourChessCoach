import { QUALITY, type Quality } from '../chess/quality'
import css from './QualityBadge.module.css'

/** A round mark with a symbol; the Russian word is the label and the tooltip. */
export function QualityBadge({ kind, className = '' }: { kind: Quality; className?: string }) {
  const { symbol, word } = QUALITY[kind]
  return (
    <span className={`${css.badge} ${className}`} data-quality={kind} role="img" aria-label={word} title={word}>
      {symbol}
    </span>
  )
}
