import { expect, test, type Locator, type Page } from '@playwright/test'
import { Chess } from 'chess.js'

type Block = { type: string; fen?: string; solution?: string[] }

test.describe('lessons', () => {
  let press: (l: Locator) => Promise<void>

  test.beforeEach(({ hasTouch }) => {
    press = (l) => (hasTouch ? l.tap() : l.click())
  })

  async function openLesson(page: Page): Promise<Block[]> {
    await page.goto('/lessons')
    await expect(page.getByRole('heading', { name: 'Уровень 1' })).toBeVisible()
    const resp = page.waitForResponse((r) => r.url().endsWith('/api/lessons/board-and-moves'))
    await press(page.getByRole('link', { name: /Доска и ходы фигур/ }).last())
    const lesson = (await (await resp).json()) as { segments: Block[] }
    await expect(page.getByTestId('position-0')).toBeVisible()
    return lesson.segments.filter((s) => s.type === 'chess')
  }

  test('solve the first position', async ({ page }) => {
    const pos = (await openLesson(page))[0]
    const chess = new Chess(pos.fen)
    const box = page.getByTestId('position-0')
    const sol = pos.solution!
    for (let i = 0; i < sol.length; i += 2) {
      const m = chess.move(sol[i])
      await press(box.locator(`[data-square="${m.from}"]`))
      await press(box.locator(`[data-square="${m.to}"]`))
      if (i + 1 < sol.length) chess.move(sol[i + 1])
    }
    await expect(box.getByTestId('status')).toHaveText('Верно!', { timeout: 10_000 })
    await expect(box.getByText('Решено')).toBeVisible()
  })

  // Mock the coach: it classifies the alternative first move.
  const mockCoach = (page: Page, classification: string) =>
    page.route('**/api/coach/move', (r) => r.fulfill({ json: { facts: { classification, lesson: null }, explanation: null } }))

  async function playAlternative(page: Page, classification: string) {
    const pos = (await openLesson(page))[0]
    const alt = new Chess(pos.fen).moves({ verbose: true }).find((m) => m.san !== pos.solution![0] && !m.promotion)!
    await mockCoach(page, classification)
    const box = page.getByTestId('position-0')
    await press(box.locator(`[data-square="${alt.from}"]`))
    await press(box.locator(`[data-square="${alt.to}"]`))
    return box
  }

  test('a best-rated alternative first move is accepted', async ({ page }) => {
    const box = await playAlternative(page, 'best')
    await expect(box.getByTestId('status')).toContainText('Тоже верно!')
    await expect(box.getByText('Решено')).toBeVisible()
  })

  test('a mistaken alternative first move is rejected', async ({ page }) => {
    const box = await playAlternative(page, 'mistake')
    await expect(box.getByTestId('status')).toContainText('Не совсем')
  })

  test('wrong move shows a message', async ({ page }) => {
    const pos = (await openLesson(page))[0]
    await page.route('**/api/coach/move', (r) => r.fulfill({ status: 500, body: 'x' }))
    const chess = new Chess(pos.fen)
    const bad = chess.moves({ verbose: true }).find((m) => m.san !== pos.solution![0] && !m.promotion)!
    const box = page.getByTestId('position-0')
    await press(box.locator(`[data-square="${bad.from}"]`))
    await press(box.locator(`[data-square="${bad.to}"]`))
    await expect(box.getByTestId('status')).toContainText('Не совсем')
  })

  test('iPhone: no horizontal overflow, board fits', async ({ page }, info) => {
    test.skip(info.project.name !== 'iphone')
    await openLesson(page)
    const a8 = (await page.locator('[data-square="a8"]').first().boundingBox())!
    const h1 = (await page.locator('[data-square="h1"]').first().boundingBox())!
    expect(a8.x).toBeGreaterThanOrEqual(0)
    expect(h1.x + h1.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })

  test.describe('line block', () => {
    const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    const moves = [
      { san: 'e4', text: 'Первое объяснение.' },
      { san: 'e5', text: 'Второе объяснение.' },
      { san: 'Nf3', text: 'Третье объяснение.' },
    ]
    const lesson = {
      slug: 'line-demo',
      number: 99,
      title: 'Линия',
      level: 1,
      themes: ['opening'],
      prerequisites: [],
      solved: [],
      segments: [{ type: 'line', title: 'Главная линия', fen: START, side: 'white', moves }],
    }

    test.beforeEach(async ({ page }) => {
      await page.route('**/api/lessons/line-demo', (r) => r.fulfill({ json: lesson }))
      await page.goto('/lessons/line-demo')
      await expect(page.getByTestId('line')).toBeVisible()
    })

    test('step forward and jump by the move list', async ({ page }) => {
      const explain = page.getByTestId('line-explain')
      await press(page.getByRole('button', { name: 'Вперёд' }))
      await press(page.getByRole('button', { name: 'Вперёд' }))
      await expect(explain).toContainText('Второе объяснение.')
      await expect(page.locator('[data-last="true"]')).toHaveText('e5')
      await press(page.getByRole('button', { name: 'Вперёд' }))
      await expect(explain).toContainText('Линия пройдена')
      await press(page.getByRole('button', { name: 'e4' }))
      await expect(explain).toContainText('Первое объяснение.')
      await expect(explain).not.toContainText('Линия пройдена')
      await press(page.getByRole('button', { name: 'Назад' }))
      await expect(explain).not.toContainText('объяснение.')
      await press(page.getByRole('button', { name: 'Вперёд' }))
      await press(page.getByRole('button', { name: 'В начало' }))
      await expect(page.getByRole('button', { name: 'Назад' })).toBeDisabled()
    })

    test('iPhone: line viewer has no horizontal overflow', async ({ page }, info) => {
      test.skip(info.project.name !== 'iphone')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      const box = (await page.getByRole('button', { name: 'Вперёд' }).boundingBox())!
      expect(box.width).toBeGreaterThanOrEqual(44)
      expect(box.height).toBeGreaterThanOrEqual(44)
    })
  })
})
