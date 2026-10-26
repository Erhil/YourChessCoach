import { expect, test, type Locator, type Page } from '@playwright/test'

const PGN = '1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#'
const pasteButton = (page: Page) =>
  page.locator('section', { hasText: 'Вставьте PGN' }).getByRole('button', { name: 'Разобрать' })


test('review pasted PGN: key moment, position, navigation, bad PGN', async ({ page, hasTouch }) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await page.goto('/review')
  await page.getByLabel('Вставьте PGN').fill(PGN)
  await press(page.getByLabel('Я играл чёрными'))
  await press(pasteButton(page))
  const moment = page.getByTestId('key-moment').first()
  await expect(moment).toContainText('♘f6??', { timeout: 20_000 })
  await expect(moment.getByRole('complementary', { name: 'Тренер' })).not.toBeEmpty()
  await press(moment.getByRole('button', { name: 'Показать позицию' }))
  // the played move (red) and the best line (green, then red)
  await expect(page.locator('[data-arrows="3"]')).toBeVisible()
  await expect(page.locator('marker polygon')).toHaveCount(3)
  await press(page.getByRole('button', { name: 'В конец' }))
  await expect(page.locator('[data-square="f7"] [data-piece="wQ"]')).toBeVisible()
  await press(page.getByRole('button', { name: 'В начало' }))
  await expect(page.locator('[data-square="e2"] [data-piece="wP"]')).toBeVisible()

  await page.getByLabel('Вставьте PGN').fill('not a pgn')
  await press(pasteButton(page))
  await expect(page.getByText('Не удалось прочитать PGN')).toBeVisible({ timeout: 20_000 })
})

test('review a saved game', async ({ page, request, hasTouch }) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const res = await request.post('/api/games', {
    data: { pgn: PGN, player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  expect(res.ok()).toBeTruthy()
  await page.goto('/review')
  const row = page.locator('li', { hasText: 'чёрными' }).first()
  await expect(row).toBeVisible()
  await press(row.getByRole('button', { name: 'Разобрать' }))
  await expect(page.getByRole('button', { name: 'В конец' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Неточности:')).toBeVisible()
  await page.reload() // Safari may reload the tab
  await expect(page.getByRole('button', { name: 'В конец' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Неточности:')).toBeVisible()
})

test('review opens a saved game from ?game=', async ({ page, request }) => {
  test.setTimeout(60_000)
  const res = await request.post('/api/games', {
    data: { pgn: PGN, player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  const { id } = (await res.json()) as { id: number }
  await page.goto(`/review?game=${id}`)
  await expect(page.getByRole('button', { name: 'В конец' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Неточности:')).toBeVisible()
})
