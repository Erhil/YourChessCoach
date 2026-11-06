import { expect, test, type Locator, type Page } from '@playwright/test'

const moves = (page: Page) => page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')
const answer = {
  facts: { classification: 'blunder', lesson: null, best_move: { uci: 'd2d4', san: 'd4' } },
  explanation: { text: 'Позднее объяснение.', source: 'template' },
}

async function start(page: Page, press: (l: Locator) => Promise<void>) {
  await page.goto('/settings')
  await page.getByLabel('Помощь тренера').selectOption('1')
  await page.goto('/play')
  await page.getByLabel('Цвет').selectOption('white')
  await press(page.getByRole('button', { name: 'Начать', exact: true }))
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
}

test('hidden coach cannot delay opponent; final save includes late facts', async ({ page, hasTouch }) => {
  const press = (l: Locator) => hasTouch ? l.tap() : l.click()
  let release!: () => void
  const held = new Promise<void>((resolve) => { release = resolve })
  let requestLevel: number | undefined
  await page.route('**/api/coach/move', async (route) => {
    requestLevel = route.request().postDataJSON().help_level
    await held
    await route.fulfill({ json: answer })
  })
  try {
    await start(page, press)
    await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
    expect(requestLevel).toBe(1)
    await press(page.getByRole('button', { name: 'Сдаться', exact: true }))
    await press(page.getByRole('button', { name: 'Да', exact: true }))
    await expect(page.getByText('Ожидают сохранения:', { exact: false })).toBeVisible()
    const saved = page.waitForRequest((r) => r.url().endsWith('/api/games') && r.method() === 'POST')
    release()
    expect((await saved).postDataJSON().blunders).toBe(1)
    await expect(page.getByRole('button', { name: 'Разобрать партию' })).toBeVisible()
    await expect(page.getByText('Позднее объяснение.')).toBeHidden()
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }
})

test('late facts after undo cannot count against the replacement move', async ({ page, hasTouch }) => {
  const press = (l: Locator) => hasTouch ? l.tap() : l.click()
  let release!: () => void
  const held = new Promise<void>((resolve) => { release = resolve })
  let first = true
  await page.route('**/api/coach/move', async (route) => {
    if (first) {
      first = false
      await held
      await route.fulfill({ json: answer })
    } else await route.fulfill({ json: { ...answer, facts: { ...answer.facts, classification: 'good' } } })
  })
  try {
    await start(page, press)
    await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
    await press(page.getByRole('button', { name: 'Ход назад', exact: true }))
    await expect(moves(page)).toHaveCount(0)
    await press(page.locator('[data-square="d2"]'))
    await press(page.locator('[data-square="d4"]'))
    await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
    release()
    await page.unrouteAll({ behavior: 'wait' })
    await press(page.getByRole('button', { name: 'Сдаться', exact: true }))
    const saved = page.waitForRequest((r) => r.url().endsWith('/api/games') && r.method() === 'POST')
    await press(page.getByRole('button', { name: 'Да', exact: true }))
    expect((await saved).postDataJSON().blunders).toBe(0)
    await expect(page.getByText('Позднее объяснение.')).toBeHidden()
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }
})


test('late facts belong to the abandoned game after a new game and navigation', async ({ page, hasTouch }) => {
  const press = (l: Locator) => hasTouch ? l.tap() : l.click()
  let release!: () => void
  const held = new Promise<void>((resolve) => { release = resolve })
  let first = true
  await page.route('**/api/coach/move', async (route) => {
    if (first) {
      first = false
      await held
      await route.fulfill({ json: answer })
    } else await route.fulfill({ json: { ...answer, facts: { ...answer.facts, classification: 'good' } } })
  })
  try {
    await start(page, press)
    await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
    await press(page.getByRole('button', { name: 'Новая партия', exact: true }))
    await press(page.getByRole('button', { name: 'Да', exact: true }))
    await press(page.getByRole('button', { name: 'Начать', exact: true }))
    if (await page.getByRole('button', { name: 'Меню', exact: true }).isVisible()) await press(page.getByRole('button', { name: 'Меню', exact: true }))
    await press(page.getByRole('link', { name: 'Уроки', exact: true }))
    const saved = page.waitForRequest((r) => r.url().endsWith('/api/games') && r.method() === 'POST')
    release()
    expect((await saved).postDataJSON().blunders).toBe(1)
    await page.unrouteAll({ behavior: 'wait' })
    if (await page.getByRole('button', { name: 'Меню', exact: true }).isVisible()) await press(page.getByRole('button', { name: 'Меню', exact: true }))
    await press(page.getByRole('link', { name: 'Игра', exact: true }))
    await expect(moves(page)).toHaveCount(0)
    await expect(page.getByText('Позднее объяснение.')).toBeHidden()
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }
})
