import { expect, test, type Locator, type Page } from '@playwright/test'

const moves = (page: Page) => page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')
const panel = (page: Page) => page.getByRole('complementary', { name: 'Тренер' })
const arrowCount = (page: Page, n: number) => expect(page.locator(`[data-arrows="${n}"]`)).toBeVisible()
const TEXT = 'Вы подставили пешку.'

const answer = (classification: string) => ({
  facts: {
    classification,
    lesson: null,
    best_move: { san: 'd4', uci: 'd2d4' },
    best_line: ['d4'],
    refutation: ['e5'],
  },
  explanation: { text: TEXT, source: 'template' },
})

async function start(page: Page, level: number, classification: string, press: (l: Locator) => Promise<void>) {
  await page.route('**/api/coach/move', (r) => r.fulfill({ json: answer(classification) }))
  await page.route('**/api/coach/hint', (r) =>
    r.fulfill({
      json: { threat: { san: 'Nxe5', uci: 'f3e5', wins: 'коня', mate: false }, best: { san: 'Nf3', uci: 'g1f3', piece: 'N' } },
    }),
  )
  await page.goto('/settings')
  await page.getByLabel('Помощь тренера').selectOption(String(level))
  await page.goto('/play')
  await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
  await page.getByLabel('Уровень').selectOption('800')
  await press(page.getByRole('button', { name: 'Начать' }))
}

async function play(page: Page, press: (l: Locator) => Promise<void>) {
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
}

for (const [level, shown] of [
  [1, false],
  [3, true],
] as const) {
  test(`level ${level}: a blunder ${shown ? 'shows' : 'does not show'} the coach panel`, async ({ page, hasTouch }) => {
    const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
    await start(page, level, 'blunder', press)
    await play(page, press)
    if (shown) await expect(panel(page)).toBeVisible()
    else {
      await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
      await expect(panel(page)).toBeHidden()
      await expect(page.getByRole('button', { name: 'Подсказка' })).toBeHidden()
    }
  })
}

test('level 5: a note after a good move, the opponent still replies', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await start(page, 5, 'good', press)
  await play(page, press)
  await expect(panel(page)).toContainText(TEXT)
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Играть дальше' })).toBeHidden()
})

test('level 5: the arrows of a note are not drawn on the position after the reply', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await start(page, 5, 'good', press)
  await play(page, press)
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await expect(panel(page)).toContainText(TEXT)
  await press(page.getByRole('button', { name: 'Показать на доске' }))
  // the note is about the move before the reply: only the threat arrow of the new position stays
  await expect(page.locator('[data-arrow-squares="f3e5"]')).toBeVisible()
})

test('hint: threat, piece, best move; the game counts it', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await start(page, 3, 'good', press)
  const hint = page.getByRole('button', { name: 'Подсказка' })
  await press(hint)
  await expect(page.getByText('Угроза: если её не заметить, соперник может сыграть ♘xe5 и забрать коня.')).toBeVisible()
  await arrowCount(page, 1)
  await press(hint)
  await expect(page.getByText('Ходите: конь')).toBeVisible()
  await arrowCount(page, 1)
  await press(hint)
  await arrowCount(page, 2)
  await expect(page.getByText('подсказок: 1')).toBeVisible()
})

test('«Показать на доске» draws the reply and the better move', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await start(page, 3, 'blunder', press)
  await play(page, press)
  await expect(panel(page)).toBeVisible()
  await press(page.getByRole('button', { name: 'Показать на доске' }))
  await arrowCount(page, 2)
})
