import { expect, test, type Locator, type Page } from '@playwright/test'

const moves = (page: Page) => page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')
const TEXT = 'Вы подставили пешку.'

const answer = (classification: string) => ({
  facts: { classification, lesson: { slug: '07-blunder-check', title: 'Проверка на зевок' } },
  explanation: { text: TEXT, source: 'template' },
})

async function setup(page: Page, classification: string, press: (l: Locator) => Promise<void>, warn = false) {
  await page.route('**/api/coach/move', (r) => r.fulfill({ json: answer(classification) }))
  if (warn) {
    await page.goto('/settings')
    await page.getByLabel('Помощь тренера').selectOption('4')
  }
  await page.goto('/play')
  await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
  await page.getByLabel('Уровень').selectOption('800')
  await press(page.getByRole('button', { name: 'Начать' }))
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
}

test('a mistake shows the coach panel; take back empties the move list', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await setup(page, 'blunder', press)
  await expect(page.getByText(TEXT)).toBeVisible()
  await expect(moves(page)).toHaveCount(1)
  await press(page.getByRole('button', { name: 'Взять ход назад' }))
  await expect(moves(page)).toHaveCount(0)
  await expect(page.getByText(TEXT)).toBeHidden()
})

test('a good move: no panel, the opponent replies', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await setup(page, 'good', press)
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
  await expect(page.getByText(TEXT)).toBeHidden()
})

test('warning mode: think again plays nothing, play anyway plays the move', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await setup(page, 'blunder', press, true)
  await expect(page.getByText('Осторожно: похоже, этот ход — зевок.')).toBeVisible()
  await press(page.getByRole('button', { name: 'Подумать ещё' }))
  await expect(moves(page)).toHaveCount(0)
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await press(page.getByRole('button', { name: 'Всё равно сходить' }))
  await expect(moves(page)).toHaveCount(1)
  await expect(page.getByText(TEXT)).toBeVisible()
  await press(page.getByRole('button', { name: 'Играть дальше' }))
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
})
