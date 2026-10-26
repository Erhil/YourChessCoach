import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { adminApi, userApi } from './helpers.ts'

// Each test has its own new user: the review list must show only the games of this test.
test.use({ storageState: { cookies: [], origins: [] } })

const NOTE = 'Тренировочная партия: были возвраты хода или подсказки. В счёт побед она не идёт.'
const moves = (page: Page) => page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')

let press: (l: Locator) => Promise<void>
let api: APIRequestContext
let admin: APIRequestContext

let verdict: string
let threats: number

test.beforeEach(async ({ page, playwright, baseURL, hasTouch }) => {
  press = (l) => (hasTouch ? l.tap() : l.click())
  admin = await adminApi(playwright.request, baseURL!)
  const user = await userApi(playwright.request, baseURL!, admin, 'training')
  api = user.ctx
  await page.context().addCookies((await api.storageState()).cookies)
  // A real engine verdict near a threshold could hold the reply; the coach says `verdict`.
  verdict = 'good'
  await page.route('**/api/coach/move', (route) =>
    route.fulfill({
      json: {
        facts: { classification: verdict, lesson: null, best_move: { san: 'd4', uci: 'd2d4' }, best_line: ['d4'], refutation: ['e5'] },
        explanation: { text: 'Вы подставили пешку.', source: 'template' },
      },
    }),
  )
  // The threat comes only `threats` times; then the position has no threat.
  threats = 1
  await page.route('**/api/coach/hint', (route) =>
    route.fulfill({
      json: {
        threat: threats-- > 0 ? { san: 'Nxe5', uci: 'f3e5', wins: 'коня', mate: false } : null,
        best: { san: 'Nf3', uci: 'g1f3', piece: 'N' },
      },
    }),
  )
})
test.afterEach(async () => {
  await api.dispose()
  await admin.dispose()
})

/** Starts a game as White at the help level `level`. */
async function begin(page: Page, level = 3) {
  await page.addInitScript((l) => localStorage.setItem('coach.helpLevel', l), String(level))
  await page.goto('/play')
  await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
  await page.getByLabel('Уровень').selectOption('800')
  await press(page.getByRole('button', { name: 'Начать' }))
}

async function play(page: Page, from: string, to: string) {
  await press(page.locator(`[data-square="${from}"]`))
  await press(page.locator(`[data-square="${to}"]`))
  await expect(moves(page)).toHaveCount(2, { timeout: 15_000 })
}

/** Leaves the game with moves: it is saved as unfinished. Returns the body of the save request. */
async function leaveAndSave(page: Page) {
  // Wait for the answer: the review list must not load before the game is stored.
  const saved = page.waitForResponse((r) => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/games')
  await press(page.getByRole('button', { name: 'Новая партия' }))
  await press(page.getByRole('button', { name: 'Да', exact: true }))
  const res = await saved
  expect(res.ok()).toBe(true)
  return res.request().postDataJSON() as { takebacks: number; hints: number }
}

async function reviewList(page: Page) {
  await page.goto('/review')
  const item = page.getByRole('listitem').filter({ has: page.getByRole('button', { name: 'Разобрать' }) })
  await expect(item).toHaveCount(1)
  return item
}

test('a takeback makes a training game: note, saved count, label in the review list', async ({ page }) => {
  await begin(page)
  await play(page, 'e2', 'e4')
  await expect(page.getByText(NOTE)).toBeHidden()
  await press(page.getByRole('button', { name: 'Ход назад' }))
  await expect(moves(page)).toHaveCount(0)
  await expect(page.getByText(NOTE)).toBeVisible()
  await play(page, 'd2', 'd4')
  const body = await leaveAndSave(page)
  expect(body.takebacks).toBe(1)
  expect(body.hints).toBe(0)
  await expect(await reviewList(page)).toContainText('тренировочная')
})

test('right after a takeback the same move can be played again', async ({ page }) => {
  await begin(page)
  await play(page, 'e2', 'e4')
  // No wait after the takeback: the tap comes while the board still animates the change.
  await press(page.getByRole('button', { name: 'Ход назад' }))
  await play(page, 'e2', 'e4')
  await expect(moves(page).first()).toHaveText(/e4/)
})

test('a reload keeps the training note and the takeback count', async ({ page }) => {
  await begin(page)
  await play(page, 'e2', 'e4')
  await press(page.getByRole('button', { name: 'Ход назад' }))
  await expect(moves(page)).toHaveCount(0)
  await play(page, 'd2', 'd4')
  await page.reload()
  await expect(moves(page)).toHaveCount(2)
  await expect(page.getByText(NOTE)).toBeVisible()
  const body = await leaveAndSave(page)
  expect(body.takebacks).toBe(1)
})

test('«Взять ход назад» after a blunder counts as a takeback', async ({ page }) => {
  verdict = 'blunder'
  await begin(page, 3)
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await press(page.getByRole('button', { name: 'Взять ход назад' }))
  await expect(moves(page)).toHaveCount(0)
  await expect(page.getByText(NOTE)).toBeVisible()
  verdict = 'good'
  await play(page, 'd2', 'd4')
  const body = await leaveAndSave(page)
  expect(body.takebacks).toBe(1)
  expect(body.hints).toBe(0)
})

test('«Подумать ещё» after a blunder warning counts as a takeback', async ({ page }) => {
  verdict = 'blunder'
  await begin(page, 4)
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await press(page.getByRole('button', { name: 'Подумать ещё' }))
  await expect(page.getByText(NOTE)).toBeVisible()
  verdict = 'good'
  await play(page, 'd2', 'd4')
  const body = await leaveAndSave(page)
  expect(body.takebacks).toBe(1)
  expect(body.hints).toBe(0)
})

test('a hint makes a training game', async ({ page }) => {
  await begin(page, 3)
  await press(page.getByRole('button', { name: 'Подсказка' }))
  await expect(page.getByText(NOTE)).toBeVisible()
  await play(page, 'e2', 'e4')
  const body = await leaveAndSave(page)
  expect(body.takebacks).toBe(0)
  expect(body.hints).toBe(1)
  await expect(await reviewList(page)).toContainText('тренировочная')
})

test('level 5: the automatic threat arrow counts as one hint', async ({ page }) => {
  await begin(page, 5)
  await expect(page.locator('[data-arrow-squares="f3e5"]')).toBeVisible()
  await expect(page.getByText(NOTE)).toBeVisible()
  await play(page, 'e2', 'e4')
  const body = await leaveAndSave(page)
  expect(body.takebacks).toBe(0)
  expect(body.hints).toBe(1)
})

test('a game with no takebacks and no hints: no note, sends 0 and 0, no label', async ({ page }) => {
  await begin(page)
  await play(page, 'e2', 'e4')
  await expect(page.getByText(NOTE)).toBeHidden()
  const body = await leaveAndSave(page)
  expect(body.takebacks).toBe(0)
  expect(body.hints).toBe(0)
  await expect(await reviewList(page)).not.toContainText('тренировочная')
})
