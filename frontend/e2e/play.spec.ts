import { expect, test, type Locator, type Page } from '@playwright/test'

const moves = (page: Page) => page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')

// The coach panel is tested in coach.spec.ts. Here a real engine verdict near a threshold
// could hold the opponent's reply and make the move count flaky, so the coach says "good".
test.beforeEach(async ({ page }) => {
  await page.route('**/api/coach/move', (route) =>
    route.fulfill({
      json: { facts: { classification: 'good', lesson: null, best_move: null }, explanation: null },
    }),
  )
})

async function open(page: Page, color: string) {
  await page.goto('/play')
  await page.getByLabel('Цвет').selectOption({ label: color })
  await page.getByLabel('Уровень').selectOption('800')
}

test('play as white, take back, play on', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const sq = (s: string) => page.locator(`[data-square="${s}"]`)
  await open(page, 'Белые')
  await press(page.getByRole('button', { name: 'Начать' }))
  await press(sq('e2'))
  await press(sq('e4'))
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await press(page.getByRole('button', { name: 'Ход назад' }))
  await expect(moves(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Ход назад' })).toBeDisabled()

  await press(sq('d2'))
  await press(sq('d4'))
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await press(sq('g1'))
  await press(sq('f3'))
  await expect(moves(page)).toHaveCount(4, { timeout: 15_000 })
})

test('play as black: opponent moves first, board is turned', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await open(page, 'Чёрные')
  await press(page.getByRole('button', { name: 'Начать' }))
  await expect(moves(page)).toHaveCount(1, { timeout: 15_000 })
  const a1 = (await page.locator('[data-square="a1"]').boundingBox())!
  const h8 = (await page.locator('[data-square="h8"]').boundingBox())!
  expect(a1.x).toBeGreaterThan(h8.x)
  expect(a1.y).toBeLessThan(h8.y)
})

test('iPhone: board fits the screen, no horizontal scroll', async ({ page }, info) => {
  test.skip(info.project.name !== 'iphone')
  await open(page, 'Белые')
  const a8 = (await page.locator('[data-square="a8"]').boundingBox())!
  const h1 = (await page.locator('[data-square="h1"]').boundingBox())!
  const width = page.viewportSize()!.width
  expect(a8.x).toBeGreaterThanOrEqual(0)
  expect(h1.x + h1.width).toBeLessThanOrEqual(width)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  // The page clips overflow, so scrollWidth does not see a control cut at the edge.
  for (const select of await page.locator('select').all()) {
    const box = (await select.boundingBox())!
    expect(box.x + box.width).toBeLessThanOrEqual(width)
  }
})

test('new game over a game with moves saves it', async ({ page, request, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await open(page, 'Белые')
  await press(page.getByRole('button', { name: 'Начать' }))
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await press(page.getByRole('button', { name: 'Новая партия' }))
  await press(page.getByRole('button', { name: 'Да' }))
  await expect
    .poll(async () => ((await (await request.get('/api/games')).json()) as unknown[]).length)
    .toBeGreaterThanOrEqual(1)
})

test('evaluation bar shows a beginner text', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop')
  await page.goto('/play')
  await page.getByLabel('Шкала оценки').check()
  await expect(
    page.getByTestId('eval').getByText(/Примерно равно|Чуть лучше|Лучше у|выигрывают|Мат в/),
  ).toBeVisible({ timeout: 15_000 })
})

test('iPhone: «Начать» is in view before the game starts', async ({ page }, info) => {
  test.skip(info.project.name !== 'iphone')
  await page.goto('/play')
  const box = (await page.getByRole('button', { name: 'Начать' }).boundingBox())!
  expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height)
})
