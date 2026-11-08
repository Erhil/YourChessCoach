import { expect, test, type Locator, type Page } from '@playwright/test'

const QUESTIONS: [string, string, number][] = [
  ['Почему ход плохой?', 'Ответ: потеряна пешка.', 1],
  ['Что угрожает?', 'Ответ: соперник берёт пешку.', 1],
  ['Что надо было делать?', 'Ответ: лучше было сходить конём.', 3],
]
const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const SQUARES = ['e2e4', 'e2e4', 'e2e4 e7e5 g1f3']

async function mockAsk(page: Page) {
  await page.route('**/api/coach/ask', async (r) => {
    const body = r.request().postDataJSON() as { question: string; text?: string }
    if (body.question === 'free') {
      return r.fulfill({ json: { answer: `Свой: ${body.text}`, source: 'template', line: null, reason: null } })
    }
    const [, answer, n] = QUESTIONS.find(([label]) => body.question === KEY[label])!
    const moves = ['e4', 'e5', 'Nf3'].slice(0, n)
    return r.fulfill({ json: { answer, source: 'template', line: { fen: START, moves }, reason: null } })
  })
}
const KEY: Record<string, string> = {
  'Почему ход плохой?': 'why',
  'Что угрожает?': 'threat',
  'Что надо было делать?': 'better',
}

async function askAll(page: Page, panel: Locator, press: (l: Locator) => Promise<void>) {
  for (const [i, [label, answer, n]] of QUESTIONS.entries()) {
    await press(panel.getByRole('button', { name: label }))
    await expect(panel.getByText(answer)).toBeVisible()
    await expect(page.locator(`[data-arrows="${n}"]`)).toBeVisible()
    await expect(page.locator(`[data-arrow-squares="${SQUARES[i]}"]`)).toBeVisible()
    const box = await panel.getByRole('button', { name: label }).boundingBox()
    expect(box!.height).toBeGreaterThanOrEqual(44)
  }
}

test('play panel: three questions show answers and arrows; free question', async ({
  page,
  hasTouch,
}) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await mockAsk(page)
  await page.route('**/api/coach/move', (r) =>
    r.fulfill({
      json: {
        facts: { classification: 'blunder', lesson: null },
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
  const panel = page.getByRole('complementary', { name: 'Тренер' })
  await askAll(page, panel, press)
  await panel.getByLabel('Свой вопрос тренеру').fill('А если иначе?')
  await press(panel.getByRole('button', { name: 'Спросить' }))
  await expect(panel.getByText('Свой: А если иначе?')).toBeVisible()
})

test('review key moment: questions show answers and arrows', async ({ page, hasTouch }) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await mockAsk(page)
  await page.goto('/review')
  await page.getByLabel('Вставьте PGN').fill('1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#')
  await press(page.getByLabel('Я играл чёрными'))
  await press(page.locator('section', { hasText: 'Вставьте PGN' }).getByRole('button', { name: 'Разобрать' }))
  const moment = page.getByTestId('key-moment').first()
  await expect(moment).toContainText('♘f6??', { timeout: 20_000 })
  await askAll(page, moment, press)
})

test('review shows each coach line on its starting position and clears it on a flip', async ({
  page,
  hasTouch,
}) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await page.goto('/review')
  await page.getByLabel('Вставьте PGN').fill('1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#')
  await press(page.getByLabel('Я играл чёрными'))
  await press(page.locator('section', { hasText: 'Вставьте PGN' }).getByRole('button', { name: 'Разобрать' }))
  const moment = page.getByTestId('key-moment').first()
  await expect(moment).toContainText('♘f6??', { timeout: 20_000 })
  await press(page.getByRole('button', { name: 'В начало' }))
  await press(moment.getByRole('button', { name: 'Показать позицию' }))
  const knightBefore = page.locator('[data-square="g8"] [data-piece="bN"]')
  const knightAfter = page.locator('[data-square="f6"] [data-piece="bN"]')
  const queen = page.locator('[data-square="h5"] [data-piece="wQ"]')
  const flip = page.getByRole('button', { name: 'Перевернуть доску' })
  await expect(knightBefore).toBeVisible()
  await press(moment.getByRole('button', { name: 'Что угрожает?' }))
  await expect(page.locator('[data-arrow-squares="h5f7"]')).toBeVisible()
  await expect(knightAfter).toBeVisible()
  await press(flip)
  await expect(page.locator('[data-arrows="0"]')).toBeVisible()
  await expect(knightAfter).toBeVisible()
  await expect(queen).toBeVisible()
  await press(flip)
  await press(moment.getByRole('button', { name: 'Что надо было делать?' }))
  await expect(page.locator('[data-arrow-squares^="g7g6"]')).toBeVisible()
  await expect(knightBefore).toBeVisible()
  await press(flip)
  await expect(page.locator('[data-arrows="0"]')).toBeVisible()
  await expect(knightBefore).toBeVisible()
  await expect(queen).toBeVisible()
})

test('review: a free question that names a move gets a template answer with that move (LLM off)', async ({
  page,
  hasTouch,
}) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await page.goto('/review')
  await page.getByLabel('Вставьте PGN').fill('1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#')
  await press(page.getByLabel('Я играл чёрными'))
  await press(page.locator('section', { hasText: 'Вставьте PGN' }).getByRole('button', { name: 'Разобрать' }))
  const moment = page.getByTestId('key-moment').first()
  await expect(moment).toContainText('♘f6??', { timeout: 20_000 })
  await moment.getByLabel('Свой вопрос тренеру').fill('Что если Nf6?')
  await press(moment.getByRole('button', { name: 'Спросить' }))
  await expect(moment.getByRole('status')).toContainText('♘f6', { timeout: 20_000 })
})
