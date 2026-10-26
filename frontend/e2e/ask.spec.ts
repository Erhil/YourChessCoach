import { expect, test, type Page } from '@playwright/test'

const health = (available: boolean) => ({
  status: 'ok',
  version: 'test',
  engines: { stockfish: { available: true, path: null } },
  llm: { enabled: true, model: 'fake', available },
})

async function open(page: Page, available: boolean) {
  await page.route('**/api/health', (r) => r.fulfill({ json: health(available) }))
  await page.goto('/lessons/board-and-moves')
  await expect(page.getByTestId('position-0')).toBeVisible()
}

test('ask the coach shows the answer', async ({ page, hasTouch }) => {
  let body: { question: string; position?: number } | undefined
  await page.route('**/api/lessons/*/ask', (r) => {
    body = r.request().postDataJSON()
    return r.fulfill({ json: { answer: 'Конь ходит буквой Г.', source: 'llm', reason: null } })
  })
  await open(page, true)
  await page.getByLabel('Ваш вопрос тренеру').fill('Как ходит конь?')
  await page.getByLabel('О какой позиции?').selectOption({ label: 'Позиция 1' })
  const send = page.getByRole('button', { name: 'Спросить' })
  await (hasTouch ? send.tap() : send.click())
  await expect(page.getByText('Конь ходит буквой Г.')).toBeVisible()
  await expect(page.getByText('тренер (ИИ)')).toBeVisible()
  expect(body).toEqual({ question: 'Как ходит конь?', position: 0 })
})

test('the reason is shown when there is no answer', async ({ page, hasTouch }) => {
  await page.route('**/api/lessons/*/ask', (r) =>
    r.fulfill({ json: { answer: null, source: null, reason: 'Тренер сейчас недоступен' } }),
  )
  await open(page, true)
  await page.getByLabel('Ваш вопрос тренеру').fill('Что такое мат?')
  const send = page.getByRole('button', { name: 'Спросить' })
  await (hasTouch ? send.tap() : send.click())
  await expect(page.getByText('Тренер сейчас недоступен')).toBeVisible()
})

test('no ask form when the LLM is unavailable', async ({ page }) => {
  await open(page, false)
  await expect(page.getByRole('link', { name: 'К списку уроков' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Спросить' })).toHaveCount(0)
})
