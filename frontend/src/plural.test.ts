import { describe, expect, it } from 'vitest'
import { plural } from './plural'

const forms = (one: string, few: string, many: string) => (n: number) => `${n} ${plural(n, one, few, many)}`

describe('plural', () => {
  it('agrees «карточка» with the number', () => {
    expect([1, 2, 5, 11, 12, 21, 22, 25, 111].map(forms('карточка', 'карточки', 'карточек'))).toEqual([
      '1 карточка', '2 карточки', '5 карточек', '11 карточек', '12 карточек', '21 карточка', '22 карточки', '25 карточек', '111 карточек',
    ])
  })
  it('agrees «повторение» with the number', () => {
    expect([0, 1, 3, 10, 14, 101].map(forms('повторение', 'повторения', 'повторений'))).toEqual([
      '0 повторений', '1 повторение', '3 повторения', '10 повторений', '14 повторений', '101 повторение',
    ])
  })
  it('agrees «неделю» and «день» with the number', () => {
    expect([1, 2, 5].map(forms('неделю', 'недели', 'недель'))).toEqual(['1 неделю', '2 недели', '5 недель'])
    expect([3, 5, 21].map(forms('день', 'дня', 'дней'))).toEqual(['3 дня', '5 дней', '21 день'])
  })
})
