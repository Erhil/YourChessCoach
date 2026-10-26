/** The Russian word form after a number: plural(5, 'карточка', 'карточки', 'карточек') → 'карточек'. */
export function plural(n: number, one: string, few: string, many: string): string {
  const d = n % 10
  if (n % 100 >= 11 && n % 100 <= 14) return many
  return d === 1 ? one : d >= 2 && d <= 4 ? few : many
}
