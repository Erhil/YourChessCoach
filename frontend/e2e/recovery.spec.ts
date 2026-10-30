import { expect, test, type Locator } from '@playwright/test'
import { adminApi, userApi } from './helpers.ts'

test.use({ storageState: { cookies: [], origins: [] } })

test.beforeEach(async ({ page, playwright, baseURL, context }) => {
  await page.addInitScript(() => { Object.defineProperty(crypto, 'randomUUID', { value: undefined }) })
  const admin = await adminApi(playwright.request, baseURL!)
  const user = await userApi(playwright.request, baseURL!, admin, 'recovery')
  await context.addCookies(await user.ctx.cookies())
  await page.goto('/play')
  await page.evaluate((login) => {
    localStorage.setItem(`play.game:${login}`, JSON.stringify({ id: 1, color: 'white', level: 800, sans: ['e4', 'e5'] }))
  }, user.login)
  await page.reload()
  await user.ctx.dispose()
  await admin.dispose()
})

for (const lostResponse of [false, true]) {
  test(`reload retries a save exactly once (server committed: ${lostResponse})`, async ({ page, hasTouch }) => {
    const press = (l: Locator) => hasTouch ? l.tap() : l.click()
    let fail = true
    let committedId: number | undefined
    await page.route('**/api/games', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      if (fail) {
        if (lostResponse) committedId = (await (await route.fetch()).json()).id
        return route.abort()
      }
      await route.continue()
    })
    await press(page.getByRole('button', { name: 'Сдаться', exact: true }))
    await press(page.getByRole('button', { name: 'Да', exact: true }))
    await expect(page.getByRole('alert').filter({ hasText: 'Партию не удалось сохранить.' })).toBeVisible()
    await page.reload()
    await expect(page.getByText('Ожидают сохранения: 1.')).toBeVisible()
    fail = false
    await press(page.getByRole('button', { name: 'Повторить сохранение' }))
    await expect(page.getByRole('button', { name: 'Повторить сохранение' })).toHaveCount(0)
    const games = await (await page.request.get('/api/games')).json()
    expect(games).toHaveLength(1)
    if (lostResponse) expect(games[0].id).toBe(committedId)
  })
}

test('two failed saves survive a new game and reload', async ({ page, hasTouch }) => {
  const press = (l: Locator) => hasTouch ? l.tap() : l.click()
  let fail = true
  await page.route('**/api/games', (route) => route.request().method() === 'POST' && fail ? route.abort() : route.continue())
  await page.route('**/api/opponent/move', (route) => route.fulfill({ json: { uci: 'e7e5', san: 'e5', engine: 'test' } }))
  await page.route('**/api/coach/move', (route) => route.fulfill({ json: { facts: { classification: 'good' } } }))
  await press(page.getByRole('button', { name: 'Новая партия' }))
  await press(page.getByRole('button', { name: 'Да', exact: true }))
  await press(page.getByRole('button', { name: 'Начать', exact: true }))
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await expect(page.locator('ol[aria-label="Ходы партии"]')).toContainText('e5')
  await press(page.getByRole('button', { name: 'Сдаться', exact: true }))
  await press(page.getByRole('button', { name: 'Да', exact: true }))
  await expect(page.getByText('Ожидают сохранения: 2.')).toBeVisible()
  await page.reload()
  fail = false
  await press(page.getByRole('button', { name: 'Повторить сохранение' }))
  await expect(page.getByRole('button', { name: 'Повторить сохранение' })).toHaveCount(0)
  expect(await (await page.request.get('/api/games')).json()).toHaveLength(2)
})


test('late save success after route remount preserves the newer failed save', async ({ page, hasTouch }) => {
  const press = (l: Locator) => hasTouch ? l.tap() : l.click()
  const navigate = async (name: string) => {
    const menu = page.getByRole('button', { name: 'Меню' })
    if (await menu.isVisible()) await press(menu)
    await press(page.getByRole('link', { name, exact: true }))
  }
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  let calls = 0
  let retry = false
  await page.route('**/api/games', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    if (++calls === 1) {
      await gate
      return route.fulfill({ json: { id: 123 } })
    }
    return retry ? route.continue() : route.abort()
  })
  await page.route('**/api/opponent/move', (route) => route.fulfill({ json: { uci: 'e7e5', san: 'e5', engine: 'test' } }))
  await page.route('**/api/coach/move', (route) => route.fulfill({ json: { facts: { classification: 'good' } } }))
  await press(page.getByRole('button', { name: 'Новая партия' }))
  await press(page.getByRole('button', { name: 'Да', exact: true }))
  await expect.poll(() => calls).toBe(1)
  await navigate('Уроки')
  await navigate('Игра')
  await press(page.getByRole('button', { name: 'Начать', exact: true }))
  await press(page.locator('[data-square="e2"]'))
  await press(page.locator('[data-square="e4"]'))
  await expect(page.locator('ol[aria-label="Ходы партии"]')).toContainText('e5')
  await press(page.getByRole('button', { name: 'Сдаться', exact: true }))
  await press(page.getByRole('button', { name: 'Да', exact: true }))
  await expect(page.getByRole('alert')).toContainText('не удалось сохранить')
  const completed = page.waitForResponse((r) => r.url().endsWith('/api/games') && r.request().method() === 'POST')
  release()
  await (await completed).finished()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await page.reload()
  await expect(page.getByText('Ожидают сохранения: 1.')).toBeVisible()
  retry = true
  await press(page.getByRole('button', { name: 'Повторить сохранение' }))
  await expect(page.getByRole('button', { name: 'Повторить сохранение' })).toHaveCount(0)
  const games = await (await page.request.get('/api/games')).json()
  expect(games).toHaveLength(1)
  expect(games[0].termination).toBe('resign')
})

for (const unavailableReads of [false, true]) {
  test(`failed device storage warns and retains an in-memory retry (reads unavailable: ${unavailableReads})`, async ({ page, hasTouch }) => {
    const press = (l: Locator) => hasTouch ? l.tap() : l.click()
    await page.evaluate((unavailableReads) => {
      if (unavailableReads) {
        Object.defineProperty(Storage.prototype, 'length', { get() { throw new DOMException('Blocked', 'SecurityError') } })
        const getItem = Storage.prototype.getItem
        Storage.prototype.getItem = function (key) {
          if (key.startsWith('play.pending:')) throw new DOMException('Blocked', 'SecurityError')
          return getItem.call(this, key)
        }
      }
      const original = Storage.prototype.setItem
      Storage.prototype.setItem = function (key, value) {
        if (key.startsWith('play.pending:')) throw new DOMException('Full', 'QuotaExceededError')
        original.call(this, key, value)
      }
    }, unavailableReads)
    let fail = true
    await page.route('**/api/games', (route) => route.request().method() === 'POST' && fail ? route.abort() : route.continue())
    await press(page.getByRole('button', { name: 'Сдаться', exact: true }))
    await press(page.getByRole('button', { name: 'Да', exact: true }))
    await expect(page.getByRole('alert').filter({ hasText: 'Партию не удалось сохранить.' })).toBeVisible()
    await expect(page.getByText('Не удалось сохранить партии на устройстве.', { exact: false })).toBeVisible()
    await expect(page.getByText('Партии сохранены на этом устройстве.', { exact: false })).toHaveCount(0)
    fail = false
    await press(page.getByRole('button', { name: 'Повторить сохранение' }))
    await expect(page.getByRole('button', { name: 'Повторить сохранение' })).toHaveCount(0)
    expect(await (await page.request.get('/api/games')).json()).toHaveLength(1)
  })

}

test('late puzzle feedback cannot replace the next puzzle feedback or rating', async ({ page, hasTouch }) => {
  const press = (l: Locator) => hasTouch ? l.tap() : l.click()
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  let puzzle = 0
  let coachCalls = 0
  const delayed: Promise<void>[] = []
  await page.route('**/api/puzzles/rating', (route) => route.fulfill({ json: { overall: 1000 } }))
  await page.route('**/api/puzzles/next*', (route) => route.fulfill({ json: {
    id: `fake-${++puzzle}`, fen: 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
    opponent_move: 'e2e4', solution: ['e7e5'], rating: 1000, themes: [], player_color: 'black', user_rating: 1000,
  } }))
  await page.route('**/api/puzzles/*/attempt', async (route) => {
    const first = route.request().url().includes('fake-1')
    if (first) await gate
    await route.fulfill({ json: { rating_before: 1000, rating_after: first ? 111 : 990, delta: first ? -889 : -10 } })
  })
  await page.route('**/api/coach/move', async (route) => {
    const first = ++coachCalls === 1
    if (first) await gate
    await route.fulfill({ json: { facts: { classification: 'mistake' }, explanation: { text: first ? 'OLD FEEDBACK' : 'CURRENT FEEDBACK' } } })
  })
  page.on('response', (response) => {
    if (response.url().includes('/attempt') || response.url().includes('/coach/move')) delayed.push(response.finished().then(() => {}))
  })
  await page.goto('/puzzles')
  await expect(page.getByTestId('status')).toContainText('Ваш ход')
  await press(page.locator('[data-square="d7"]'))
  await press(page.locator('[data-square="d5"]'))
  await expect(page.getByTestId('status')).toHaveText('Неверно')
  await press(page.getByRole('button', { name: 'Следующая задача' }))
  await expect(page.getByTestId('status')).toContainText('Ваш ход')
  await press(page.locator('[data-square="d7"]'))
  await press(page.locator('[data-square="d5"]'))
  await expect(page.getByText('CURRENT FEEDBACK')).toBeVisible()
  await expect(page.getByText('Ваш рейтинг: 990')).toBeVisible()
  const lateResponses = Promise.all([
    page.waitForResponse((r) => r.url().includes('fake-1/attempt')),
    page.waitForResponse((r) => r.url().includes('/coach/move')),
  ])
  release()
  await lateResponses
  await Promise.all(delayed)
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await expect(page.getByText('CURRENT FEEDBACK')).toBeVisible()
  await expect(page.getByText('Ваш рейтинг: 990')).toBeVisible()
  await expect(page.getByText('OLD FEEDBACK')).toHaveCount(0)
})
