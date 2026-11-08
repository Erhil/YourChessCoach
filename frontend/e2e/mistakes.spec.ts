import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { adminApi, userApi } from './helpers.ts'

const rnd = (n: number) => 1 + Math.floor(Math.random() * n)

/** White wins the queen with Rd1xd5. Two spare pawns at random squares make the position unique. */
function freshFen(): string {
  const w = `${'abc'[rnd(3) - 1]}${rnd(5) + 1}`
  const b = `${'fgh'[rnd(3) - 1]}${rnd(5) + 2}`
  const rows: string[][] = Array.from({ length: 8 }, () => Array<string>(8).fill('1'))
  const put = (sq: string, p: string) => (rows[8 - Number(sq[1])][sq.charCodeAt(0) - 97] = p)
  put('e8', 'k'); put('d5', 'q'); put('d1', 'R'); put('e1', 'K'); put(w, 'P'); put(b, 'p')
  const board = rows.map((r) => r.join('').replace(/1+/g, (s) => String(s.length))).join('/')
  return `${board} w - - 0 1`
}

const NEXT = /\/api\/mistakes\/next\?/

/** Creates a card and makes the page show exactly this card. */
async function openCard(page: Page, request: APIRequestContext, played: { uci: string; san: string } | null = null) {
  const fen = freshFen()
  const created = await request.post('/api/mistakes', {
    data: { source: 'play', fen, best_uci: 'd1d5', classification: 'blunder', played_uci: played?.uci },
  })
  const { id } = (await created.json()) as { id: number }
  const card = { id, review_version: 0, fen, side: 'white', source: 'play', motif: null, classification: 'blunder', played_san: played?.san ?? null }
  // The page asks /api/mistakes/next?tz=…: a glob without the query does not match it.
  await page.route(NEXT, (r) => r.fulfill({ json: { card, due: 1, today: { reviewed: 0, limit: 10 } } }))
  await page.goto('/mistakes')
}

test.describe('mistakes deck', () => {
  // Each test has its own new user: parallel profiles answer the cards and change the due count of the shared user.
  test.use({ storageState: { cookies: [], origins: [] } })
  let press: (l: Locator) => Promise<void>
  let play: (page: Page, from: string, to: string) => Promise<void>
  let request: APIRequestContext
  let admin: APIRequestContext

  test.afterEach(async () => {
    await request.dispose()
    await admin.dispose()
  })

  test.beforeEach(async ({ page, playwright, baseURL, hasTouch }) => {
    admin = await adminApi(playwright.request, baseURL!)
    request = (await userApi(playwright.request, baseURL!, admin, 'deck')).ctx
    await page.context().addCookies((await request.storageState()).cookies)
    press = (l) => (hasTouch ? l.tap() : l.click())
    play = async (page, from, to) => {
      await press(page.locator(`[data-square="${from}"]`))
      await press(page.locator(`[data-square="${to}"]`))
    }
  })

  test('the best move is correct', async ({ page }) => {
    await openCard(page, request)
    await expect(page.getByTestId('deck-today')).toHaveText('1 на сегодня')
    await expect(page.getByText('Из игры с тренером')).toBeVisible()
    await play(page, 'd1', 'd5')
    await expect(page.getByTestId('status')).toContainText('Верно!', { timeout: 15_000 })
    await expect(page.getByTestId('status')).toContainText('До трёх повторений: ещё 2 правильных ответа.')
    await expect(page.getByTestId('status')).toContainText('Следующее повторение через 1 день.')
    await expect(page.getByTestId('status')).not.toContainText('Ваш ход тоже хороший')
    await expect(page.locator('[data-arrows="1"]')).toBeVisible()
  })

  test('a lost answer response reloads the committed deck without resending', async ({ page }) => {
    await openCard(page, request)
    await page.unroute(NEXT)
    let answers = 0
    await page.route('**/api/mistakes/*/answer*', async (route) => {
      answers++
      const response = await route.fetch()
      expect(response.status()).toBe(200)
      await route.abort('failed')
    })
    await play(page, 'd1', 'd5')
    await expect(page.getByText('Ответ мог сохраниться. Колода обновлена; продолжайте с доступной карточки.')).toBeVisible()
    await expect(page.getByTestId('status')).toContainText('На сегодня всё повторено.')
    expect(answers).toBe(1)
    const deck = await (await request.get('/api/mistakes/next?tz=0')).json() as { card: unknown; today: { reviewed: number } }
    expect(deck.card).toBeNull()
    expect(deck.today.reviewed).toBe(1)
    await page.reload()
    await expect(page.getByTestId('status')).toContainText('На сегодня всё повторено.')
    expect(answers).toBe(1)
  })

  test('a wrong move shows the best move and an explanation', async ({ page }) => {
    await openCard(page, request)
    await play(page, 'e1', 'f1')
    await expect(page.getByTestId('status')).toHaveText('Не тот ход. Лучше было ♖xd5. Карточка вернётся сегодня.', {
      timeout: 15_000,
    })
    await expect(page.getByRole('complementary', { name: 'Тренер' })).not.toBeEmpty()
    await expect(page.locator('[data-arrows="2"]')).toBeVisible() // played move (red) and best move (green)
  })

  test('the card shows the move played in the game', async ({ page }) => {
    await openCard(page, request, { uci: 'e1f1', san: 'Kf1' })
    await expect(page.getByTestId('deck-played')).toHaveText('В партии вы сыграли ♔f1')
  })

  test('a card without the played move has no such line', async ({ page }) => {
    await openCard(page, request)
    await expect(page.getByTestId('status')).toHaveText('Найдите лучший ход')
    await expect(page.getByTestId('deck-played')).toHaveCount(0)
  })

  test('a good move that is not the best is right, and the best is named', async ({ page }) => {
    await openCard(page, request)
    await page.route('**/api/mistakes/*/answer*', (r) =>
      r.fulfill({
        json: { correct: true, best_uci: 'd1d5', best_san: 'Rxd5', streak: 1, left: 2, learned: false, due_at: new Date(Date.now() + 86_400_000).toISOString(), explanation: null },
      }),
    )
    await play(page, 'e1', 'f1')
    await expect(page.getByTestId('status')).toContainText('Верно! Ваш ход тоже хороший, лучший — ♖xd5. До трёх повторений: ещё 2 правильных ответа.')
    await expect(page.locator('[data-arrows="1"]')).toBeVisible() // only the best move
  })

  test('a wrong answer keeps the card due', async ({ page }) => {
    await openCard(page, request)
    // The real due count of the test's own user: the page shows the stubbed /next count, so it cannot prove anything.
    const due = async () => ((await (await request.get('/api/mistakes/stats')).json()) as { due: number }).due
    const before = await due()
    const answered = page.waitForResponse((r) => r.url().includes('/answer'))
    await play(page, 'e1', 'f1')
    const body = (await (await answered).json()) as { correct: boolean; streak: number; learned: boolean; due_at: string }
    expect(body).toMatchObject({ correct: false, streak: 0, learned: false })
    expect(Date.parse(body.due_at)).toBeLessThan(Date.now() + 60_000) // due today, not tomorrow
    await expect(page.getByTestId('status')).toContainText('Карточка вернётся сегодня.', { timeout: 15_000 })
    // The count of due cards does not drop (other tests may add cards, so it may grow).
    expect(await due()).toBeGreaterThanOrEqual(before)
    expect(before).toBeGreaterThanOrEqual(1)
  })

  test('the last right answer marks the mistake as learned', async ({ page }) => {
    await openCard(page, request)
    await page.route('**/api/mistakes/*/answer*', (r) =>
      r.fulfill({
        json: { correct: true, best_uci: 'd1d5', best_san: 'Rxd5', streak: 3, left: 0, learned: true, due_at: '2026-01-01T00:00:00Z', explanation: null },
      }),
    )
    await play(page, 'd1', 'd5')
    await expect(page.getByTestId('status')).toContainText('Верно! Три повторения пройдены.')
  })

  test('«Усвоено» shows only when a card is learned, and there is no total', async ({ page }) => {
    await openCard(page, request)
    await expect(page.getByTestId('status')).toHaveText('Найдите лучший ход')
    await expect(page.getByTestId('deck-stats')).toHaveCount(0)
    await expect(page.getByText('Всего в колоде')).toHaveCount(0)
    await page.route('**/api/mistakes/stats', (r) => r.fulfill({ json: { total: 4, due: 1, learned: 2 } }))
    await page.reload()
    await expect(page.getByTestId('deck-stats')).toHaveText('Три повторения пройдены: 2')
  })

  test('the daily limit of 1 uses the singular', async ({ page }) => {
    await page.route(NEXT, (r) => r.fulfill({ json: { card: null, due: 3, today: { reviewed: 1, limit: 1 } } }))
    await page.goto('/mistakes')
    await expect(page.getByTestId('status')).toHaveText('На сегодня всё: вы сделали 1 повторение. Возвращайтесь завтра.')
  })

  test('one right answer left uses the singular', async ({ page }) => {
    await openCard(page, request)
    await page.route('**/api/mistakes/*/answer*', (r) =>
      r.fulfill({
        json: { correct: true, best_uci: 'd1d5', best_san: 'Rxd5', streak: 2, left: 1, learned: false, due_at: new Date(Date.now() + 3 * 86_400_000).toISOString(), explanation: null },
      }),
    )
    await play(page, 'd1', 'd5')
    await expect(page.getByTestId('status')).toContainText('До трёх повторений: ещё 1 правильный ответ. Следующее повторение через 3 дня.')
  })

  test('the daily limit: «N на сегодня», then «На сегодня всё»', async ({ page }) => {
    await openCard(page, request)
    await expect(page.getByTestId('deck-today')).toHaveText('1 на сегодня')
    await page.unroute(NEXT)
    await page.route(NEXT, (r) => r.fulfill({ json: { card: null, due: 3, today: { reviewed: 10, limit: 10 } } }))
    await page.reload()
    await expect(page.getByTestId('status')).toHaveText('На сегодня всё: вы сделали 10 повторений. Возвращайтесь завтра.')
    await expect(page.getByTestId('deck-today')).toHaveCount(0)
  })

  test('an empty deck keeps its own text', async ({ page }) => {
    await page.goto('/mistakes')
    await expect(page.getByTestId('status')).toHaveText('На сегодня всё повторено. Карточек в колоде: 0')
  })
})

test('saving a game adds the blunder to the deck once', async ({ page, hasTouch, playwright, baseURL, context }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const admin = await adminApi(playwright.request, baseURL!)
  const user = await userApi(playwright.request, baseURL!, admin, 'play-card')
  await context.addCookies(await user.ctx.cookies())
  await user.ctx.dispose()
  await admin.dispose()
  await page.route('**/api/coach/move', (r) =>
    r.fulfill({
      json: {
        facts: { classification: 'blunder', lesson: null, best_move: { san: 'd4', uci: 'd2d4' } },
        explanation: { text: 'Вы подставили пешку.', source: 'template' },
      },
    }),
  )
  await page.goto('/play')
  await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
  await page.getByLabel('Уровень').selectOption('800')
  await press(page.getByRole('button', { name: 'Начать' }))
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await expect(page.getByText('Вы подставили пешку.')).toBeVisible()
  expect(await (await page.request.get('/api/mistakes/stats')).json()).toMatchObject({ total: 0 })
  await press(page.getByRole('button', { name: 'Сдаться', exact: true }))
  await press(page.getByRole('button', { name: 'Да', exact: true }))
  await expect(page.getByRole('button', { name: 'Разобрать партию' })).toBeVisible()
  const next = await (await page.request.get('/api/mistakes/next')).json()
  expect(next).toMatchObject({ due: 1, card: { played_san: 'e4', classification: 'blunder' } })
})
