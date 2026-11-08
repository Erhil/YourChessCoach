import { expect, test, type Locator } from '@playwright/test'
import { Chess } from 'chess.js'
import { adminApi, userApi } from './helpers.ts'

type Block = { type: string; fen?: string; solution?: string[] }
type Puzzle = { solution: string[] }
type Card = { card: { fen: string } | null }

test.use({ storageState: { cookies: [], origins: [] } })

test('user journey: lesson, puzzle, game, review, mistakes deck', async ({ page, playwright, baseURL, hasTouch }) => {
  test.setTimeout(180_000)
  const admin = await adminApi(playwright.request, baseURL!)
  try {
    const user = await userApi(playwright.request, baseURL!, admin, 'journey')
    try {
      await page.context().addCookies((await user.ctx.storageState()).cookies)
    } finally {
      await user.ctx.dispose()
    }
  } finally {
    await admin.dispose()
  }
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const sq = (s: string) => page.locator(`[data-square="${s}"]`)
  const status = page.getByTestId('status')
  const go = async (name: string) => {
    const menu = page.getByRole('button', { name: 'Меню' })
    if (await menu.isVisible()) await press(menu)
    await press(page.getByRole('navigation', { name: 'Разделы' }).getByRole('link', { name, exact: true }))
    await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  }

  // Lesson: first position.
  await page.goto('/')
  await expect(page.getByRole('region', { name: 'Задания дня' })).toBeVisible({ timeout: 15_000 })
  await go('Уроки')
  const lessonResp = page.waitForResponse((r) => r.url().endsWith('/api/lessons/board-and-moves'))
  await press(page.getByRole('link', { name: /Доска и ходы фигур/ }).last())
  const pos = ((await (await lessonResp).json()) as { segments: Block[] }).segments.filter((s) => s.type === 'chess')[0]
  const box = page.getByTestId('position-0')
  await expect(box).toBeVisible()
  const chess = new Chess(pos.fen)
  const sol = pos.solution!
  for (let i = 0; i < sol.length; i += 2) {
    const m = chess.move(sol[i])
    await press(box.locator(`[data-square="${m.from}"]`))
    await press(box.locator(`[data-square="${m.to}"]`))
    if (i + 1 < sol.length) chess.move(sol[i + 1])
  }
  await expect(box.getByTestId('status')).toHaveText('Верно!', { timeout: 10_000 })

  // Puzzle.
  const puzzleResp = page.waitForResponse((r) => r.url().includes('/api/puzzles/next'))
  await go('Задачи')
  const pz = (await (await puzzleResp).json()) as Puzzle
  await expect(status).toContainText('Ваш ход', { timeout: 10_000 })
  for (let i = 0; i < pz.solution.length; i += 2) {
    const uci = pz.solution[i]
    await press(sq(uci.slice(0, 2)))
    await press(sq(uci.slice(2, 4)))
    if (uci.length === 5) await press(page.locator(`[data-promotion="${uci[4]}"]`))
    if (i + 1 < pz.solution.length) {
      await expect(status).toContainText('Соперник ходит')
      await expect(status).toContainText('Ваш ход', { timeout: 10_000 })
    }
  }
  await expect(status).toHaveText('Решено!')

  // Game: one move, opponent replies.
  await go('Профиль')
  await page.getByLabel('Помощь тренера').selectOption('3')
  await go('Игра')
  await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
  await page.getByLabel('Уровень').selectOption('800')
  await press(page.getByRole('button', { name: 'Начать' }))
  await press(sq('e2'))
  await press(sq('e4'))
  await expect(page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')).toHaveCount(2, { timeout: 20_000 })

  // The game survives a reload; a hint draws an arrow.
  await page.reload()
  await expect(page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Начать', exact: true })).toBeHidden()
  const hint = page.getByRole('button', { name: 'Подсказка' })
  for (let i = 0; i < 3 && !(await page.locator('[data-arrows]:not([data-arrows="0"])').first().isVisible()); i++) await press(hint)
  await expect(page.locator('[data-arrows]:not([data-arrows="0"])').first()).toBeVisible()

  // Opening lesson: line viewer, one step.
  await page.goto('/lessons/italian-game-white')
  await expect(page.getByTestId('line').first()).toBeVisible()
  await press(page.getByRole('button', { name: 'Вперёд' }).first())
  await expect(page.getByTestId('line-explain').first()).toContainText('e4')

  // Finished game with a blunder, then review it.
  const created = await page.request.post('/api/games', {
    data: {
      pgn: '1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#',
      player_color: 'black',
      level: 800,
      result: '1-0',
      termination: 'checkmate',
    },
  })
  expect(created.ok()).toBeTruthy()
  await go('Разбор партии')
  await expect(page.getByRole('heading', { name: 'Мои партии' })).toBeVisible()
  const row = page.locator('li', { hasText: 'чёрными' }).first()
  await press(row.getByRole('button', { name: 'Разобрать' }))
  await expect(page.getByTestId('key-moment').first()).toBeVisible({ timeout: 20_000 })
  const moment = page.getByTestId('key-moment').first()
  const why = moment.getByRole('button', { name: 'Почему ход плохой?' })
  await expect(why).toBeHidden()
  await press(moment.getByRole('button', { name: 'Показать позицию' }))
  await press(why)
  const answer = moment.getByRole('status').last()
  await expect(answer).toHaveText(/\S{3,}/)
  await expect(answer).not.toContainText('недоступен')

  // Mistakes deck: a card is due, answer it.
  const cardResp = page.waitForResponse((r) => r.url().includes('/api/mistakes/next'))
  await go('Колода ошибок')
  const { card } = (await (await cardResp).json()) as Card
  expect(card).not.toBeNull()
  const mv = new Chess(card!.fen).moves({ verbose: true })[0]
  await press(sq(mv.from))
  await press(sq(mv.to))
  await expect(status).toContainText(/Верно!|Не тот ход/, { timeout: 20_000 })
})
