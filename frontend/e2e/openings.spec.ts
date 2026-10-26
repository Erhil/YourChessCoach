import { expect, test, type Locator, type Page } from '@playwright/test'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const lesson = {
  slug: 'line-demo',
  number: 99,
  title: 'Линия',
  level: 1,
  themes: ['opening'],
  prerequisites: [],
  solved: [],
  segments: [
    {
      type: 'line',
      title: 'Главная линия',
      fen: START,
      side: 'white',
      moves: [
        { san: 'e4', text: 'Первое объяснение.' },
        { san: 'e5', text: 'Второе объяснение.' },
        { san: 'Nf3', text: 'Третье объяснение.' },
      ],
    },
  ],
}

test.describe('openings', () => {
  let press: (l: Locator) => Promise<void>
  let play: (page: Page, from: string, to: string) => Promise<void>

  test.beforeEach(({ hasTouch }) => {
    press = (l) => (hasTouch ? l.tap() : l.click())
    play = async (page, from, to) => {
      await press(page.locator(`[data-square="${from}"]`))
      await press(page.locator(`[data-square="${to}"]`))
    }
  })

  async function train(page: Page) {
    await page.route('**/api/lessons/line-demo', (r) => r.fulfill({ json: lesson }))
    await page.goto('/lessons/line-demo')
    await press(page.getByRole('button', { name: 'Потренироваться' }))
    await expect(page.getByTestId('line-trainer')).toBeVisible()
  }

  test('trainer: student moves, opponent replies, line done', async ({ page }) => {
    await train(page)
    await play(page, 'e2', 'e4')
    await expect(page.getByText('Первое объяснение.')).toBeVisible()
    await expect(page.getByText('Второе объяснение.')).toBeVisible({ timeout: 5_000 })
    await play(page, 'g1', 'f3')
    await expect(page.getByText('Линия пройдена!')).toBeVisible()
    await press(page.getByRole('button', { name: 'Выйти из тренировки' }))
    await expect(page.getByTestId('line')).toBeVisible()
  })

  test('trainer: a wrong move is explained by the coach and taken back', async ({ page }) => {
    await page.route('**/api/openings/name', (r) => r.fulfill({ json: null }))
    await page.route('**/api/coach/move', (r) =>
      r.fulfill({
        json: { facts: { classification: 'good', lesson: null }, explanation: { text: 'Пояснение тренера.', source: 'template' } },
      }),
    )
    await train(page)
    await play(page, 'a2', 'a3')
    await expect(page.getByLabel('Тренер')).toContainText('Этот ход не совпадает с линией урока.')
    await expect(page.getByLabel('Тренер')).toContainText('Пояснение тренера.')
    await play(page, 'e2', 'e4')
    await expect(page.getByText('Первое объяснение.')).toBeVisible()
    await expect(page.getByLabel('Тренер')).toHaveCount(0)
  })

  test('trainer: a book move is named', async ({ page }) => {
    await page.route('**/api/openings/name', (r) =>
      r.fulfill({ json: { eco: 'A00', name: 'Test Opening', exact: true } }),
    )
    await train(page)
    await play(page, 'd2', 'd4')
    await expect(page.getByLabel('Тренер')).toContainText('Это тоже известный ход: Test Opening. В уроке разбираем ход')
  })

  test('puzzles: ?opening= preselects the opening and is sent', async ({ page }) => {
    await page.route('**/api/puzzles/openings', (r) =>
      r.fulfill({ json: [{ key: 'Italian_Game', name: 'Italian Game', count: 10 }] }),
    )
    const req = page.waitForRequest((r) => r.url().includes('/api/puzzles/next'))
    await page.goto('/puzzles?opening=Italian_Game')
    expect((await req).url()).toContain('opening=Italian_Game')
    await expect(page.getByLabel('Дебют')).toHaveValue('Italian_Game')
  })

  test('play: the opening name appears', async ({ page }) => {
    let n = 0
    await page.route('**/api/opponent/move', (r) =>
      r.fulfill({ json: n++ === 0 ? { uci: 'e7e5', san: 'e5', engine: 'x' } : { uci: 'b8c6', san: 'Nc6', engine: 'x' } }),
    )
    await page.route('**/api/coach/move', (r) =>
      r.fulfill({ json: { facts: { classification: 'good', lesson: null, best_move: null }, explanation: null } }),
    )
    await page.goto('/play')
    await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
    await press(page.getByRole('button', { name: 'Начать' }))
    await play(page, 'e2', 'e4')
    await expect(page.locator('ol[aria-label="Ходы партии"] li > span:nth-child(n+2)')).toHaveCount(2, { timeout: 10_000 })
    await play(page, 'g1', 'f3')
    await expect(page.getByTestId('opening-name')).toContainText('Дебют: ', { timeout: 10_000 })
  })

  test('card: name, steps the line, continuations, puzzles link', async ({ page, hasTouch }) => {
    await page.route('**/api/openings/name', (r) =>
      r.fulfill({ json: { eco: 'C50', name: 'Итальянская партия', exact: true } }),
    )
    await page.route('**/api/openings/card?*', (r) =>
      r.fulfill({
        json: {
          eco: 'C50',
          name: 'Итальянская партия',
          line_san: ['e4', 'e5', 'Nf3', 'Nc6', 'Bc4'],
          continuations: [
            { san: 'Bc5', uci: 'f8c5', eco: 'C50', name: 'Итальянская партия: Giuoco Piano' },
            { san: 'Nf6', uci: 'g8f6', eco: 'C55', name: 'Защита двух коней' },
          ],
          lesson: { slug: 'italian-game-white', title: 'Итальянская партия: играем белыми' },
          puzzles: 'Italian_Game',
        },
      }),
    )
    await page.route('**/api/opponent/move', (r) => r.fulfill({ json: { uci: 'e7e5', san: 'e5', engine: 'x' } }))
    await page.route('**/api/coach/move', (r) =>
      r.fulfill({ json: { facts: { classification: 'good', lesson: null, best_move: null }, explanation: null } }),
    )
    await page.goto('/play')
    await page.getByLabel('Цвет').selectOption({ label: 'Белые' })
    await press(page.getByRole('button', { name: 'Начать' }))
    await play(page, 'e2', 'e4')
    // The reply comes after 300 ms; a card opened before it is rebuilt and goes back to the line end.
    await expect(page.getByRole('list', { name: 'Ходы партии' })).toContainText('e5')
    await press(page.getByTestId('opening-name'))
    const card = page.getByTestId('opening-card')
    await expect(card).toContainText('Итальянская партия (C50)')
    await expect(card.getByTestId('opening-next')).toContainText('3… ♗c5')
    await expect(card.getByTestId('opening-next')).toContainText('Защита двух коней')
    await expect(card.getByRole('link', { name: /Урок: Итальянская партия/ })).toBeVisible()
    await expect(card.getByRole('button', { name: 'Вперёд' })).toBeDisabled()
    await press(card.getByRole('button', { name: 'Назад' }))
    await expect(card.getByRole('button', { name: 'Вперёд' })).toBeEnabled()
    await press(card.getByRole('button', { name: 'В начало' }))
    await expect(card.getByRole('button', { name: 'Назад' })).toBeDisabled()
    if (!hasTouch) {
      await page.keyboard.press('Escape')
      await expect(card).toHaveCount(0)
      await press(page.getByTestId('opening-name'))
    }
    await press(page.getByTestId('opening-card').getByRole('link', { name: 'Задачи по этому дебюту' }))
    await expect(page).toHaveURL(/\/puzzles\?opening=Italian_Game/)
  })

  test('lessons: the opening sections are listed after the levels', async ({ page }) => {
    await page.goto('/lessons')
    const heading = page.getByRole('heading', { name: 'Дебюты: за белых' })
    await expect(heading).toBeVisible()
    const section = page.locator('section', { has: heading })
    await expect(section.getByRole('link', { name: /Итальянская партия: играем белыми/ })).toBeVisible()
  })
})
