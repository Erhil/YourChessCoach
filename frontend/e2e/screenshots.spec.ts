import { expect, test, type Locator } from '@playwright/test'
import { ADMIN_TOKEN } from './constants.ts'
import { uniqueLogin } from './helpers.ts'

test.skip(!process.env.SCREENSHOTS, 'set SCREENSHOTS=1 to take screenshots')

const pair = {
  item_id: 'i1',
  fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2',
  move_san: 'Qh4',
  classification: 'blunder',
  best_move_san: 'Nc6',
  a: { text: 'Первое объяснение: ферзь вышел слишком рано и его легко атаковать.' },
  b: { text: 'Второе объяснение: конь на c6 развивает фигуру и защищает пешку.' },
  token: 't1',
}
const row = (model: string, votes: number) => ({
  model, votes, wins: 1, losses: 0, ties: 0, win_rate: 0.6, valid_pct: 0.9, mean_seconds: 1.5, vram_gb: 3.2,
})

test('screenshots of every page', async ({ page, request, hasTouch }, info) => {
  test.skip(!['iphone', 'ipad', 'ipad-landscape'].includes(info.project.name))
  test.setTimeout(240_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const sq = (s: string) => page.locator(`[data-square="${s}"]`)
  let n = 0
  const shot = async (name: string) => {
    await page.waitForTimeout(400)
    await page.screenshot({ path: `test-results/screenshots/${info.project.name}/${String(++n).padStart(2, '0')}-${name}.png` })
  }
  const menu = page.getByRole('button', { name: 'Меню' })
  const go = async (name: string) => {
    if (await menu.isVisible()) await press(menu)
    await press(page.getByRole('navigation', { name: 'Разделы' }).getByRole('link', { name, exact: true }))
    await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  }

  await page.route('**/api/admin/bench/pair', (r) => r.fulfill({ json: pair }))
  await page.route('**/api/admin/bench/results', (r) =>
    r.fulfill({ json: { models: [row('qwen3.5:4b', 3), row('gemma4:e4b', 3)], default_model: 'gemma4:e4b', bench_created: 'x' } }),
  )

  await page.goto('/')
  await expect(page.getByRole('region', { name: 'Задания дня' })).toBeVisible({ timeout: 15_000 })
  await shot('today')
  if (await menu.isVisible()) {
    await press(menu)
    await expect(page.getByRole('navigation', { name: 'Разделы' })).toBeVisible()
    await shot('menu')
    await press(menu)
  }

  await go('Профиль')
  await page.getByLabel('Помощь тренера').selectOption('3')
  await go('Игра')
  await shot('play-start')
  await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
  await page.getByLabel('Уровень').selectOption('800')
  await press(page.getByRole('button', { name: 'Начать' }))
  await press(sq('e2'))
  await press(sq('e4'))
  await expect(page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')).toHaveCount(2, { timeout: 20_000 })
  await shot('play')
  const hint = page.getByRole('button', { name: 'Подсказка' })
  for (let i = 0; i < 3 && !(await page.locator('[data-arrows]:not([data-arrows="0"])').first().isVisible()); i++) await press(hint)
  await expect(page.locator('[data-arrows]:not([data-arrows="0"])').first()).toBeVisible()
  await shot('play-hint')

  await go('Задачи')
  await expect(page.getByTestId('status')).toContainText('Ваш ход', { timeout: 15_000 })
  await shot('puzzles')

  await go('Уроки')
  await expect(page.getByRole('heading', { name: 'Уровень 1' })).toBeVisible()
  await shot('lessons')
  await press(page.getByRole('link', { name: /Доска и ходы фигур/ }).last())
  await expect(page.getByTestId('position-0')).toBeVisible()
  await page.getByTestId('position-0').scrollIntoViewIfNeeded()
  await shot('lesson')

  await page.goto('/lessons/italian-game-white')
  await expect(page.getByTestId('line').first()).toBeVisible()
  await press(page.getByRole('button', { name: 'Вперёд' }).first())
  await page.getByTestId('line').first().scrollIntoViewIfNeeded()
  await shot('opening-line')
  await press(page.getByRole('button', { name: 'Потренироваться' }).first())
  await expect(page.getByTestId('line-trainer')).toBeVisible()
  await page.getByTestId('line-trainer').scrollIntoViewIfNeeded()
  await shot('opening-trainer')

  const created = await request.post('/api/games', {
    data: { pgn: '1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#', player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  expect(created.ok()).toBeTruthy()
  await go('Разбор партии')
  await press(page.locator('li', { hasText: 'чёрными' }).first().getByRole('button', { name: 'Разобрать' }))
  await expect(page.getByTestId('key-moment').first()).toBeVisible({ timeout: 20_000 })
  await page.getByTestId('key-moment').first().scrollIntoViewIfNeeded()
  await shot('review')
  const moment = page.getByTestId('key-moment').first()
  await press(moment.getByRole('button', { name: 'Что надо было делать?' }))
  await expect(moment.getByRole('status').last()).toHaveText(/\S{3,}/)
  await expect(moment.getByRole('status').last()).not.toContainText('недоступен')
  await shot('review-ask')

  await go('Колода ошибок')
  await expect(page.getByTestId('status')).toContainText('Найдите лучший ход', { timeout: 15_000 })
  await shot('mistakes')

  await go('Профиль')
  await expect(page.getByRole('heading', { name: 'Колода ошибок' })).toBeVisible()
  await shot('profile')

  await page.goto('/admin/bench')
  await expect(page.getByRole('heading', { level: 1, name: 'Сравнение моделей' })).toBeVisible()
  await expect(page.getByText('Первое объяснение')).toBeVisible()
  await expect(page.getByTestId('row-gemma4:e4b')).toBeVisible()
  await shot('bench')

  await page.goto('/settings')
  await expect(page).toHaveURL(/\/profile#settings$/)
  await expect(page.getByRole('heading', { level: 2, name: 'Настройки' })).toBeVisible()
  await shot('settings')
})

test.describe('login and admin screenshots', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('login page and admin page', async ({ page, hasTouch }, info) => {
    test.skip(!['iphone', 'ipad', 'ipad-landscape'].includes(info.project.name))
    const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
    const shot = async (name: string) => {
      await page.waitForTimeout(400)
      await page.screenshot({ path: `test-results/screenshots/${info.project.name}/${name}.png` })
    }
    await page.goto('/login')
    await expect(page.getByRole('heading', { level: 1, name: 'Вход' })).toBeVisible()
    await shot('login')

    await page.goto('/admin')
    await page.getByLabel('Токен администратора').fill(ADMIN_TOKEN)
    await press(page.getByRole('button', { name: 'Войти' }))
    await page.getByLabel('Логин нового пользователя').fill(uniqueLogin('shot'))
    await press(page.getByRole('button', { name: 'Создать пользователя' }))
    await expect(page.getByTestId('token')).toBeVisible()
    await shot('admin')
  })
})
