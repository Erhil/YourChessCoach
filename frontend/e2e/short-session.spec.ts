import { Chess } from 'chess.js'
import { expect, test, type Locator } from '@playwright/test'
import type { TrainingSession, TrainingStatus } from '../src/api/training.ts'
import { adminApi, userApi } from './helpers.ts'

test('a saved game starts a finite session and a lost reply preserves the first move', async ({
  page, playwright, baseURL, hasTouch, request,
}) => {
  test.setTimeout(60_000)
  const press = (locator: Locator) => hasTouch ? locator.tap() : locator.click()
  const admin = await adminApi(playwright.request, baseURL!)
  const user = await userApi(playwright.request, baseURL!, admin, 'training')
  try {
    // Logging in as the test user must leave the suite's shared session valid.
    expect((await request.get('/api/auth/me')).ok()).toBeTruthy()
    await page.context().clearCookies()
    await page.context().addCookies((await user.ctx.storageState()).cookies)
    const saved = await user.ctx.post('/api/games', {
      data: {
        pgn: '1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#',
        player_color: 'black', level: 800, result: '1-0', termination: 'checkmate',
      },
    })
    expect(saved.ok()).toBeTruthy()
    const { id } = (await saved.json()) as { id: number }
    const review = await user.ctx.post('/api/review', { data: { game_id: id, practice: true } })
    expect(review.ok()).toBeTruthy()

    await page.goto('/')
    const training = page.getByRole('region', { name: 'Занятие на пять минут' })
    const square = (name: string) => training.locator(`[data-square="${name}"]`)
    const actionUrl = '**/api/training/*/action'
    const retry = training.getByRole('button', { name: 'Повторить отправку' })
    const originalMove = training.getByText('Ход в партии: ♘f6.', { exact: true })
    await press(training.getByRole('button', { name: 'Начать занятие', exact: true }))
    await expect(training.getByText('Позиция из вашей партии')).toBeVisible()
    await expect(square('h5').locator('[data-piece="wQ"]')).toBeVisible()
    await expect(square('g8').locator('[data-piece="bN"]')).toBeVisible()
    await expect(training.getByRole('button', { name: 'Следующий ход решения' })).toHaveCount(0)
    await expect(originalMove).toHaveCount(0)

    const sent: unknown[] = []
    let originalText: string | null | undefined
    await page.route(actionUrl, async (route) => {
      sent.push(route.request().postDataJSON())
      if (sent.length === 1) {
        await route.fulfill({ status: 503, json: { detail: 'Stockfish unavailable' } })
      } else if (sent.length === 2) {
        const response = await route.fetch()
        expect(response.ok()).toBeTruthy()
        const result = (await response.json()) as TrainingSession
        originalText = result.feedback?.original_text
        await route.abort()
      } else {
        await route.continue()
      }
    })
    await press(square('a7'))
    await press(square('a6'))
    await expect(training.getByRole('alert')).toContainText('Stockfish сейчас недоступен')
    await press(retry)
    await expect(training.getByRole('alert')).toContainText('Не удалось связаться с сервером')
    await page.reload()
    await expect(training.getByText('Ход не засчитан.')).toBeVisible()
    await expect(originalMove).toBeVisible()
    expect(originalText).toBeTruthy()
    await expect(training.getByText(originalText!, { exact: true })).toBeVisible()
    expect(sent).toHaveLength(3)
    expect(sent[0]).toMatchObject({ expected_login: user.login, action: 'move', uci: 'a7a6' })
    expect(sent[1]).toEqual(sent[0])
    expect(sent[2]).toEqual(sent[0])
    await page.unrouteAll({ behavior: 'wait' })

    await press(training.getByRole('button', { name: 'Следующий ход решения' }))
    await expect(training.getByText(/ · 1 из /)).toBeVisible()
    const next = page.waitForResponse((response) => response.url().endsWith('/action'))
    await press(training.getByRole('button', { name: 'Следующее упражнение' }))
    const position = ((await (await next).json()) as TrainingSession).position!
    await expect(training.getByText('Незнакомое упражнение')).toBeVisible()
    await press(training.getByRole('button', { name: 'Взять подсказку' }))
    await expect(training.getByRole('button', { name: 'Взять подсказку' })).toHaveCount(0)
    const move = new Chess(position.fen).moves({ verbose: true }).find((candidate) => !candidate.promotion)!
    await press(square(move.from))
    await press(square(move.to))
    await press(training.getByRole('button', { name: 'К итогам' }))
    await expect(training.getByRole('heading', { name: 'Итог занятия' })).toBeVisible()
    await expect(training.getByText('Самостоятельно: 0 из 1 верно.')).toBeVisible()
    await expect(training.getByText(/С помощью: [01] из 1 верно/)).toBeVisible()
    await expect(training.getByText('Без ответа: 0 из 2.')).toBeVisible()

    await page.reload()
    await expect(training.getByRole('heading', { name: 'Итог занятия' })).toBeVisible()
    await expect(training.getByRole('button', { name: 'Пройти проверку после перерыва' })).toHaveCount(0)
    await press(training.getByRole('button', { name: 'Начать новое занятие' }))
    await expect(training.getByText('Позиция из вашей партии')).toBeVisible()
    await expect(originalMove).toHaveCount(0)
    await press(training.getByRole('button', { name: 'Показать решение' }))
    await expect(training.getByText('Решение показано без попытки.')).toBeVisible()
    await expect(originalMove).toBeVisible()
    await expect(training.getByText(originalText!, { exact: true })).toBeVisible()
    await press(training.getByRole('button', { name: 'Закончить занятие' }))
    await expect(training.getByRole('heading', { name: 'Итог занятия' })).toBeVisible()
    const latest = (await (await user.ctx.get('/api/training')).json()) as TrainingStatus
    expect(latest.session?.counts.unfinished).toBe(latest.session?.total)
  } finally {
    await page.unrouteAll({ behavior: 'wait' })
    await user.ctx.dispose()
    await admin.dispose()
  }
})
