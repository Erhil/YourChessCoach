import { expect, test, type Locator, type Page } from '@playwright/test'

const moves = (page: Page) => page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')
const onBoard = (page: Page, word: string) => page.locator(`[data-square] [data-quality]`).and(page.getByRole('img', { name: word }))
const inList = (page: Page, word: string) => page.locator('ol[aria-label="Ходы партии"]').getByRole('img', { name: word })
const NOTE = 'Вы упустили выгодный ход.'

async function play(page: Page, classification: string, book: boolean, press: (l: Locator) => Promise<void>) {
  await page.route('**/api/coach/move', (r) =>
    r.fulfill({
      json: {
        facts: { classification, lesson: null, best_move: null },
        explanation: { text: NOTE, source: 'template' },
      },
    }),
  )
  if (!book) await page.route('**/api/openings/name', (r) => r.fulfill({ json: null }))
  await page.goto('/play')
  await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
  await page.getByLabel('Уровень').selectOption('800')
  await press(page.getByRole('button', { name: 'Начать' }))
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
}

test('the badge shows on the board and in the move list; the switch hides it', async ({ page, hasTouch }, info) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await play(page, 'inaccuracy', false, press)
  await expect(onBoard(page, 'Неточность')).toHaveCount(1)
  await expect(inList(page, 'Неточность')).toHaveCount(1)
  await expect(page.locator('[data-square="e4"] [data-quality="inaccuracy"]')).toHaveCount(1)
  if (info.project.name === 'iphone') await page.screenshot({ path: 'test-results/screenshots/move-icons-iphone.png' })
  await press(page.getByLabel('Значки качества хода'))
  await expect(page.locator('[data-quality]')).toHaveCount(0)
  await press(page.getByLabel('Значки качества хода'))
  await expect(inList(page, 'Неточность')).toHaveCount(1)
})

test('1.e4 is a book move: the book badge replaces the engine class', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await play(page, 'blunder', true, press)
  await expect(onBoard(page, 'Дебютный ход')).toHaveCount(1)
  await expect(inList(page, 'Дебютный ход')).toHaveCount(1)
  await expect(page.locator('[data-quality="blunder"]')).toHaveCount(0)
})

test('with icons off and help level 1: no badge, no note, the blunder still goes to the deck', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await page.route('**/api/coach/move', (r) =>
    r.fulfill({
      json: {
        facts: { classification: 'blunder', lesson: null, best_move: { san: 'd4', uci: 'd2d4' } },
        explanation: { text: NOTE, source: 'template' },
      },
    }),
  )
  await page.route('**/api/openings/name', (r) => r.fulfill({ json: null }))
  await page.route('**/api/mistakes', (r) => r.fulfill({ json: { id: 1, created: true } }))
  await page.goto('/settings')
  await page.getByLabel('Помощь тренера').selectOption('1')
  await press(page.getByLabel('Значки качества хода'))
  await page.goto('/play')
  await page.getByLabel('Уровень').selectOption('800')
  await press(page.getByRole('button', { name: 'Начать' }))
  const sent = page.waitForRequest((r) => r.url().endsWith('/api/mistakes') && r.method() === 'POST')
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await sent
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await expect(page.locator('[data-quality]')).toHaveCount(0)
  await expect(page.getByText(NOTE)).toBeHidden()
})

test('help level 1 with icons on: the badge shows, no note', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await page.goto('/settings')
  await page.getByLabel('Помощь тренера').selectOption('1')
  await play(page, 'mistake', false, press)
  await expect(inList(page, 'Ошибка')).toHaveCount(1)
  await expect(page.getByText(NOTE)).toBeHidden()
})

test('a mistake does not stop the game: note shown, the opponent replies at once', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await play(page, 'mistake', false, press)
  await expect(page.getByText(NOTE)).toBeVisible()
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Играть дальше' })).toHaveCount(0)
  await press(page.getByRole('button', { name: 'Ход назад' }))
  await expect(moves(page)).toHaveCount(0)
})

test('a blunder stops the game until «Играть дальше»', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await play(page, 'blunder', false, press)
  await expect(page.getByRole('button', { name: 'Играть дальше' })).toBeVisible()
  await expect(inList(page, 'Зевок')).toHaveCount(1)
  await page.waitForTimeout(1500)
  await expect(moves(page)).toHaveCount(1)
  await press(page.getByRole('button', { name: 'Играть дальше' }))
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
})
