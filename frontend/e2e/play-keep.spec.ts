import { expect, test, type Locator, type Page } from '@playwright/test'

const moves = (page: Page) => page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')

test.beforeEach(async ({ page }) => {
  await page.route('**/api/coach/move', (route) =>
    route.fulfill({
      json: { facts: { classification: 'good', lesson: null, best_move: null }, explanation: null },
    }),
  )
})

test('the game survives a reload and the new-game question protects it', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const sq = (s: string) => page.locator(`[data-square="${s}"]`)
  const btn = (name: string) => page.getByRole('button', { name, exact: true })

  await page.goto('/play')
  await press(btn('Начать'))
  await press(sq('e2'))
  await press(sq('e4'))
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })

  await page.reload()
  await expect(moves(page)).toHaveCount(2)
  await expect(btn('Начать')).toBeHidden()
  await press(sq('d2'))
  await press(sq('d4'))
  await expect(moves(page)).toHaveCount(4, { timeout: 15_000 })

  await press(btn('Новая партия'))
  await expect(page.getByText('Текущая партия сохранится как незаконченная.')).toBeVisible()
  await press(btn('Отмена'))
  await expect(moves(page)).toHaveCount(4)
  await press(btn('Новая партия'))
  await press(btn('Да'))
  await expect(btn('Начать')).toBeVisible()
  await expect(moves(page)).toHaveCount(0)
})

test('resign ends the game and offers a review', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const btn = (name: string) => page.getByRole('button', { name, exact: true })
  await page.goto('/play')
  await press(btn('Начать'))
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await press(btn('Сдаться'))
  await expect(page.getByText('Сдаться? Партия будет записана как поражение.')).toBeVisible()
  await press(btn('Да'))
  await expect(page.getByText('Вы сдались.')).toBeVisible()
  await expect(btn('Разобрать партию')).toBeVisible()
  await expect(btn('Новая партия')).toBeVisible()
})
