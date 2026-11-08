import { expect, test, type Locator, type Page } from '@playwright/test'
import { Chess } from 'chess.js'

type Puzzle = { fen: string; opponent_move: string; solution: string[] }

async function open(page: Page): Promise<Puzzle> {
  const resp = page.waitForResponse((r) => r.url().includes('/api/puzzles/next'))
  await page.goto('/puzzles')
  return (await (await resp).json()) as Puzzle
}

const status = (page: Page) => page.getByTestId('status')
const yourTurn = (page: Page) => expect(status(page)).toContainText('Ваш ход', { timeout: 10_000 })

test.describe('puzzles', () => {
  let press: (l: Locator) => Promise<void>
  let play: (page: Page, uci: string) => Promise<void>

  test.beforeEach(({ hasTouch }) => {
    press = (l) => (hasTouch ? l.tap() : l.click())
    play = async (page, uci) => {
      await press(page.locator(`[data-square="${uci.slice(0, 2)}"]`))
      await press(page.locator(`[data-square="${uci.slice(2, 4)}"]`))
      if (uci.length === 5) await press(page.locator(`[data-promotion="${uci[4]}"]`))
    }
  })

  test('solve a puzzle', async ({ page }) => {
    const pz = await open(page)
    await yourTurn(page)
    for (let i = 0; i < pz.solution.length; i += 2) {
      await play(page, pz.solution[i])
      if (i + 1 < pz.solution.length) {
        await expect(status(page)).toContainText('Соперник ходит')
        await yourTurn(page)
      }
    }
    await expect(status(page)).toHaveText('Решено!')
    await expect(page.getByTestId('rating-change')).toContainText('Рейтинг:')
  })

  test('reload keeps the current puzzle until it is finished', async ({ page }) => {
    const pz = await open(page)
    await yourTurn(page)
    let fetched = 0
    page.on('request', (r) => {
      if (r.url().includes('/api/puzzles/next')) fetched++
    })
    await page.reload()
    await yourTurn(page)
    expect(fetched).toBe(0)
    for (let i = 0; i < pz.solution.length; i += 2) {
      await play(page, pz.solution[i])
      if (i + 1 < pz.solution.length) {
        await expect(status(page)).toContainText('Соперник ходит')
        await yourTurn(page)
      }
    }
    await expect(status(page)).toHaveText('Решено!')
    const again = page.waitForResponse((r) => r.url().includes('/api/puzzles/next'))
    await page.reload()
    await again // a solved puzzle is not kept
  })

  test('wrong move shows the explanation and the solution', async ({ page }) => {
    const pz = await open(page)
    await yourTurn(page)
    const chess = new Chess(pz.fen)
    chess.move({ from: pz.opponent_move.slice(0, 2), to: pz.opponent_move.slice(2, 4), promotion: pz.opponent_move[4] })
    const bad = chess.moves({ verbose: true }).find((m) => {
      const uci = m.from + m.to + (m.promotion ?? '')
      return uci !== pz.solution[0] && !m.promotion && !new Chess(m.after).isCheckmate()
    })!
    const request = () => page.waitForRequest((r) => /\/api\/puzzles\/[^/]+\/attempt$/.test(r.url()))
    const failed = request()
    const uci = bad.from + bad.to
    await play(page, uci)
    const first = (await failed).postDataJSON()
    expect(first).toMatchObject({ solved: false, used_hint: false, details: { ply: 1, played_uci: uci, first_uci: uci, revealed: false, elapsed_ms: expect.any(Number) } })
    await expect(status(page)).toHaveText('Неверно')
    await expect(page.getByLabel('Тренер')).toBeVisible({ timeout: 15_000 })
    const revealed = request()
    await press(page.getByRole('button', { name: 'Показать решение' }))
    await expect(status(page)).toHaveText('Решение:')
    expect((await revealed).postDataJSON()).toEqual({ ...first, details: { ...first.details, revealed: true } })
  })

  test('revealing without a move submits no invented move', async ({ page }) => {
    await open(page)
    await yourTurn(page)
    const revealed = page.waitForResponse((r) => /\/api\/puzzles\/[^/]+\/attempt$/.test(r.url()))
    await press(page.getByRole('button', { name: 'Показать решение' }))
    const response = await revealed
    expect(response.ok()).toBe(true)
    expect(response.request().postDataJSON()).toMatchObject({
      solved: false, used_hint: true, details: { ply: 1, played_uci: null, first_uci: null, revealed: true },
    })
  })

  test('analysis replays the solution from the learner position and preserves the result', async ({ page }) => {
    const pz = await open(page)
    await yourTurn(page)
    const chess = new Chess(pz.fen)
    chess.move(pz.opponent_move)
    let attempts = 0
    page.on('request', (r) => {
      if (/\/api\/puzzles\/[^/]+\/attempt$/.test(r.url())) attempts++
    })
    await press(page.getByRole('button', { name: 'Показать решение' }))
    const rating = page.getByTestId('rating-change')
    await expect(rating).toBeVisible()
    const savedRating = await rating.innerText()

    const initialAnalysis = page.waitForRequest('**/api/analyze')
    await press(page.getByRole('button', { name: 'Разобрать варианты' }))
    const analysis = page.getByRole('region', { name: 'Разбор вариантов' })
    expect((await initialAnalysis).postDataJSON()).toMatchObject({ fen: chess.fen(), multipv: 3 })
    const forward = analysis.getByRole('button', { name: 'Вперёд' })
    const back = analysis.getByRole('button', { name: 'Назад' })
    await press(forward)
    await expect(analysis.getByRole('status', { name: 'Позиция в разборе' })).toContainText('Ход 1.')
    await press(back)
    await expect(analysis.getByRole('status', { name: 'Позиция в разборе' })).toContainText('Начальная позиция.')
    await expect(forward).toBeEnabled()
    await press(analysis.getByRole('button', { name: 'Закрыть разбор' }))
    await expect(status(page)).toHaveText('Решение:')
    await expect(rating).toHaveText(savedRating)
    await expect(page.getByRole('button', { name: 'Следующая задача' })).toBeEnabled()
    expect(attempts).toBe(1)
  })

  test('hint names the piece', async ({ page }) => {
    await open(page)
    await yourTurn(page)
    await press(page.getByRole('button', { name: 'Подсказка' }))
    await expect(page.getByText(/^Ходит /)).toBeVisible()
  })

  test('second hint draws an arrow', async ({ page }) => {
    await open(page)
    await yourTurn(page)
    await expect(page.locator('[data-arrows="0"]')).toBeVisible()
    await press(page.getByRole('button', { name: 'Подсказка' }))
    await expect(page.locator('[data-arrows="0"]')).toBeVisible()
    await press(page.getByRole('button', { name: 'Подсказка' }))
    await expect(page.locator('[data-arrows="1"]')).toBeVisible()
  })

  test('iPhone: board fits the screen', async ({ page }, info) => {
    test.skip(info.project.name !== 'iphone')
    await open(page)
    await yourTurn(page) // the opponent's first move has been played; the board is stable
    await expect(page.locator('[data-square="a8"]')).toBeVisible()
    const a8 = (await page.locator('[data-square="a8"]').boundingBox())!
    const h1 = (await page.locator('[data-square="h1"]').boundingBox())!
    expect(a8.x).toBeGreaterThanOrEqual(0)
    expect(h1.x + h1.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    // A long opening name must not push its select past the content column (into the gutter).
    // Measured against <main>, not the board: under load the board can still be small here.
    const right = await page
      .locator('main')
      .evaluate((m) => m.getBoundingClientRect().right - parseFloat(getComputedStyle(m).paddingRight))
    for (const select of await page.locator('select').all()) {
      const box = (await select.boundingBox())!
      expect(box.x + box.width).toBeLessThanOrEqual(right + 1)
    }
  })
})
