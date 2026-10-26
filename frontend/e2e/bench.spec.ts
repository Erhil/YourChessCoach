import { expect, test, type Locator } from '@playwright/test'

const pair = (n: number) => ({
  item_id: `i${n}`,
  fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2',
  move_san: 'Qh4',
  classification: 'blunder',
  best_move_san: 'Nc6',
  a: { text: `Первое объяснение ${n}` },
  b: { text: `Второе объяснение ${n}` },
  token: `t${n}`,
})
const row = (model: string, votes: number) => ({
  model,
  votes,
  wins: 0,
  losses: 0,
  ties: 0,
  win_rate: 0.5,
  valid_pct: 0.9,
  mean_seconds: 1.5,
  vram_gb: 3.2,
})

test('vote grows the counter and the default model can be changed', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  let n = 1
  let votes = 0
  let def = 'm1'
  await page.route('**/api/admin/bench/pair', (r) => r.fulfill({ json: pair(n++) }))
  await page.route('**/api/admin/bench/vote', (r) => {
    expect(r.request().postDataJSON()).toEqual({ token: 't1', winner: 'a' })
    votes = 1
    return r.fulfill({ json: { votes } })
  })
  await page.route('**/api/admin/bench/results', (r) =>
    r.fulfill({
      json: { models: [row('m1', votes), row('m2', votes)], default_model: def, bench_created: 'x' },
    }),
  )
  await page.route('**/api/admin/bench/default', (r) => {
    def = r.request().postDataJSON().model
    return r.fulfill({ json: { default_model: def } })
  })
  await page.goto('/admin/bench')
  await expect(page.getByText('Первое объяснение 1')).toBeVisible()
  await expect(page.getByText(/Лучший ход: ♘c6/)).toBeVisible()
  await expect(page.getByText('Голосов: 0')).toBeVisible()
  await press(page.getByRole('button', { name: 'Лучше A' }))
  await expect(page.getByText('Голосов: 1')).toBeVisible()
  await expect(page.getByText('Первое объяснение 2')).toBeVisible()
  await expect(page.getByTestId('row-m1')).toContainText('✓')
  await press(page.getByTestId('row-m2').getByRole('button', { name: 'Сделать моделью по умолчанию' }))
  await expect(page.getByTestId('row-m2')).toContainText('✓')
  await expect(page.getByTestId('row-m1')).not.toContainText('✓')
})

test('the missing results message is shown as text', async ({ page }) => {
  const msg = 'Нет результатов сравнения. Запустите python scripts/bench_models.py'
  await page.route('**/api/admin/bench/**', (r) => r.fulfill({ status: 404, json: { detail: msg } }))
  await page.goto('/admin/bench')
  await expect(page.getByText(msg)).toBeVisible()
})
