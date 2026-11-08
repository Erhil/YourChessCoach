import { expect, test, type Locator, type Page } from '@playwright/test'

const PGN = '1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#'
const pasteButton = (page: Page) =>
  page.locator('section', { hasText: 'Вставьте PGN' }).getByRole('button', { name: 'Разобрать' })


test('review pasted PGN: key moment, position, navigation, bad PGN', async ({ page, hasTouch }) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  await page.goto('/review')
  await page.getByLabel('Вставьте PGN').fill(PGN)
  await press(page.getByLabel('Я играл чёрными'))
  await press(pasteButton(page))
  const moment = page.getByTestId('key-moment').first()
  await expect(moment).toContainText('♘f6??', { timeout: 20_000 })
  await expect(moment.getByRole('complementary', { name: 'Тренер' })).not.toBeEmpty()
  await press(moment.getByRole('button', { name: 'Показать позицию' }))
  // the played move (red) and the best line (green, then red)
  await expect(page.locator('[data-arrows="3"]')).toBeVisible()
  await expect(page.locator('marker polygon')).toHaveCount(3)
  await press(page.getByRole('button', { name: 'В конец' }))
  await expect(page.locator('[data-square="f7"] [data-piece="wQ"]')).toBeVisible()
  await press(page.getByRole('button', { name: 'В начало' }))
  await expect(page.locator('[data-square="e2"] [data-piece="wP"]')).toBeVisible()

  await page.getByLabel('Вставьте PGN').fill('not a pgn')
  await press(pasteButton(page))
  await expect(page.getByText('Не удалось прочитать PGN')).toBeVisible({ timeout: 20_000 })
})

test('review a saved game', async ({ page, request, hasTouch }) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const res = await request.post('/api/games', {
    data: { pgn: PGN, player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  expect(res.ok()).toBeTruthy()
  await page.goto('/review')
  const row = page.locator('li', { hasText: 'чёрными' }).first()
  await expect(row).toBeVisible()
  await press(row.getByRole('button', { name: 'Разобрать' }))
  await expect(page.getByRole('button', { name: 'В конец' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Неточности:')).toBeVisible()
  await page.reload() // Safari may reload the tab
  await expect(page.getByRole('button', { name: 'В конец' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Неточности:')).toBeVisible()
})

test('review opens a saved game from ?game=', async ({ page, request }) => {
  test.setTimeout(60_000)
  const res = await request.post('/api/games', {
    data: { pgn: PGN, player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  const { id } = (await res.json()) as { id: number }
  await page.goto(`/review?game=${id}`)
  await expect(page.getByRole('button', { name: 'В конец' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Неточности:')).toBeVisible()
})

test('saved review flips to the other side without another analysis', async ({ page, request, hasTouch }) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const pgn = `[SetUp "1"]
[FEN "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"]

3... Nf6 4. Nc3 a6 5. Qxf7#`
  const saved = await request.post('/api/games', {
    data: { pgn, player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  expect(saved.ok()).toBeTruthy()
  const { id } = (await saved.json()) as { id: number }
  const requests: unknown[] = []
  page.on('request', (r) => {
    if (new URL(r.url()).pathname === '/api/review') requests.push(r.postDataJSON())
  })
  await page.goto(`/review?game=${id}`)
  const moment = (title: string) => page.getByTestId('key-moment').filter({
    has: page.getByRole('heading', { name: title }),
  })
  const black = moment('Чёрные · 3... ♘f6?? — зевок')
  const white = moment('Белые · 4. ♘c3?? — зевок')
  const square = (name: string) => page.locator(`[data-square="${name}"]`)
  const firstRankOnTop = async () => (await square('a1').boundingBox())!.y < (await square('a8').boundingBox())!.y
  const list = page.getByRole('list', { name: 'Ходы партии' })
  const flip = page.getByRole('button', { name: 'Перевернуть доску' })
  const trainer = (m: Locator) => m.getByRole('complementary', { name: 'Тренер' })

  await expect(black).toBeVisible({ timeout: 20_000 })
  expect(await firstRankOnTop()).toBe(true)
  await expect(page.getByText(/Чёрные\. Неточности:.*Зевки: 2/)).toBeVisible()
  await expect(white).toHaveCount(0)
  await expect(trainer(black)).toHaveCount(0)
  await expect(list.getByRole('listitem').first()).toHaveText('3...♘f6??')
  await expect(list.getByRole('button', { name: '♘c3??' })).toBeVisible()
  await press(list.getByRole('button', { name: '♘f6??' }))
  await press(black.getByRole('button', { name: 'Показать позицию' }))
  await expect(trainer(black)).toBeVisible()
  await expect(square('g8').locator('[data-piece="bN"]')).toBeVisible()

  await press(flip)
  await expect(white).toBeVisible()
  expect(await firstRankOnTop()).toBe(false)
  await expect(black).toHaveCount(0)
  await expect(page.getByText(/Белые\. Неточности:.*Зевки: 1/)).toBeVisible()
  await expect(square('g8').locator('[data-piece="bN"]')).toBeVisible()
  await expect(page.locator('[data-arrows="0"]')).toBeVisible()
  await expect(trainer(white)).toHaveCount(0)

  await press(white.getByRole('button', { name: 'Попробовать ход' }))
  const practice = page.getByRole('region', { name: 'Самостоятельная попытка' })
  await expect(practice.getByText('Найдите хороший ход за белых.')).toBeVisible()
  expect(await firstRankOnTop()).toBe(false)
  await expect(practice.getByRole('button', { name: 'Показать решение' })).toBeVisible()
  await expect(practice.getByRole('button', { name: 'Следующий ход решения' })).toHaveCount(0)
  expect(requests).toEqual([{ game_id: id, practice: true, both_sides: true }])
})

test('saved review keeps the first attempt and checks an alternative after reveal', async ({ page, request, hasTouch }, info) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const saved = await request.post('/api/games', {
    data: { pgn: PGN, player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  expect(saved.ok()).toBeTruthy()
  const { id } = (await saved.json()) as { id: number }
  await page.goto(`/review?game=${id}`)
  const moment = page.getByTestId('key-moment').filter({ hasText: '3... ♘f6' })
  const start = moment.getByRole('button', { name: 'Попробовать ход' })
  await expect(start).toBeVisible({ timeout: 20_000 })
  await expect(moment.getByRole('complementary', { name: 'Тренер' })).toHaveCount(0)
  await press(start)
  const practice = page.getByRole('region', { name: 'Самостоятельная попытка' })
  const square = (name: string) => practice.locator(`[data-square="${name}"]`)
  await expect(practice.locator('[data-arrows="0"]')).toBeVisible()
  await expect(practice.getByRole('button', { name: 'Следующий ход решения' })).toHaveCount(0)
  const board = (await practice.locator('[data-arrows="0"]').boundingBox())!
  const reveal = (await practice.getByRole('button', { name: 'Показать решение' }).boundingBox())!
  if (info.project.name === 'ipad-landscape') {
    expect(reveal.x).toBeGreaterThanOrEqual(board.x + board.width)
    expect(reveal.y).toBeLessThan(board.y + board.height)
  } else if (info.project.name === 'ipad' || info.project.name === 'iphone') {
    expect(reveal.y).toBeGreaterThanOrEqual(board.y + board.height)
  }

  // Let a genuine reply arrive after the exercise has closed.
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/coach/move', async (route) => {
    await gate
    await route.fulfill({ response: await route.fetch() })
  })
  try {
    const checking = page.waitForRequest('**/api/coach/move')
    await press(square('g8'))
    await press(square('f6'))
    expect((await checking).postDataJSON()).toMatchObject({ move: 'g8f6', help_level: 1 })
    await expect(square('g8').locator('[data-piece="bN"]')).toBeVisible()
    await press(practice.getByRole('button', { name: 'Вернуться к разбору' }))
    await expect(practice).toHaveCount(0)
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }

  await page.reload()
  await expect(start).toBeVisible({ timeout: 20_000 })
  await press(start)
  await expect(practice.getByText('Первая самостоятельная попытка ещё не проверена.')).toBeVisible()
  await press(practice.getByRole('button', { name: 'Повторить проверку хода' }))
  await expect(practice.getByText('Первая самостоятельная попытка не засчитана.')).toBeVisible()
  await press(practice.getByRole('button', { name: 'Показать решение' }))
  await press(practice.getByRole('button', { name: 'Следующий ход решения' }))
  await expect(square('g6').locator('[data-piece="bP"]')).toBeVisible()
  await press(practice.getByRole('button', { name: 'Попробовать с помощью' }))

  // Qe7 is a strong alternative to g6 in this position.
  await press(square('d8'))
  await press(square('e7'))
  await expect(practice.getByText('Ход засчитан.', { exact: true })).toBeVisible()
  await expect(practice.getByText('Первая самостоятельная попытка не засчитана.')).toBeVisible()
  await expect(square('e7').locator('[data-piece="bQ"]')).toBeVisible()
  await press(practice.getByRole('button', { name: 'Следующий ход решения' }))
  await expect(practice.getByText(/ · 2 из /)).toBeVisible()
})

test('saved review keeps the first attempt and reveal across tabs', async ({ page, context, request, hasTouch }) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const saved = await request.post('/api/games', {
    data: { pgn: PGN, player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  expect(saved.ok()).toBeTruthy()
  const { id } = (await saved.json()) as { id: number }
  const other = await context.newPage()
  const start = (tab: Page) => tab.getByTestId('key-moment').filter({ hasText: '3... ♘f6' })
    .getByRole('button', { name: 'Попробовать ход' })
  const practice = (tab: Page) => tab.getByRole('region', { name: 'Самостоятельная попытка' })
  const play = async (tab: Page, from: string, to: string) => {
    for (const square of [from, to]) await press(practice(tab).locator(`[data-square="${square}"]`))
  }

  await page.goto(`/review?game=${id}`)
  await other.goto(`/review?game=${id}`)
  for (const tab of [page, other]) {
    await expect(start(tab)).toBeVisible({ timeout: 20_000 })
    await press(start(tab))
  }

  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/coach/move', async (route) => {
    const response = await route.fetch()
    await gate
    await route.fulfill({ response })
  })
  try {
    await play(page, 'g8', 'f6')
    const firstPending = 'Первая самостоятельная попытка ещё не проверена.'
    await expect(practice(page).getByText(firstPending)).toBeVisible()

    await play(other, 'a7', 'a6')
    await expect(practice(other).getByText('Stockfish нашёл ход сильнее.', { exact: false })).toBeVisible()
    await expect(practice(other).getByText(firstPending)).toBeVisible()
    await press(practice(other).getByRole('button', { name: 'Вернуться к разбору' }))
    await press(other.getByTestId('key-moment').filter({ hasText: '3... ♘f6' })
      .getByRole('button', { name: 'Показать позицию' }))

    release()
    const firstRejected = 'Первая самостоятельная попытка не засчитана.'
    await expect(practice(page).getByText(firstRejected)).toBeVisible()
    await other.reload()
    await expect(start(other)).toBeVisible({ timeout: 20_000 })
    await press(start(other))
    await expect(practice(other).getByText(firstRejected)).toBeVisible()
    await expect(practice(other).getByRole('button', { name: 'Попробовать с помощью' })).toBeVisible()
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }
})

test('saved review can recover a lost first verdict after another tab accepts a move', async ({ page, context, request, hasTouch }) => {
  test.setTimeout(60_000)
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const saved = await request.post('/api/games', {
    data: { pgn: PGN, player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' },
  })
  expect(saved.ok()).toBeTruthy()
  const { id } = (await saved.json()) as { id: number }
  const other = await context.newPage()
  const openPractice = async (tab: Page) => {
    const start = tab.getByTestId('key-moment').filter({ hasText: '3... ♘f6' })
      .getByRole('button', { name: 'Попробовать ход' })
    await expect(start).toBeVisible({ timeout: 20_000 })
    await press(start)
  }
  const practice = (tab: Page) => tab.getByRole('region', { name: 'Самостоятельная попытка' })
  const play = async (tab: Page, from: string, to: string) => {
    for (const square of [from, to]) await press(practice(tab).locator(`[data-square="${square}"]`))
  }

  for (const tab of [page, other]) {
    await tab.goto(`/review?game=${id}`)
    await openPractice(tab)
  }

  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/coach/move', async (route) => {
    const response = await route.fetch()
    expect(response.ok()).toBe(true)
    await gate
    await route.abort('failed')
  })
  try {
    const submitted = page.waitForRequest('**/api/coach/move')
    await play(page, 'g8', 'f6')
    expect((await submitted).postDataJSON()).toMatchObject({ move: 'g8f6' })
    await press(practice(page).getByRole('button', { name: 'Вернуться к разбору' }))
    await expect(practice(page)).toHaveCount(0)
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }

  const box = practice(other)
  await play(other, 'd8', 'e7')
  await expect(box.getByText('Ход засчитан.', { exact: true })).toBeVisible()
  await other.reload()
  await openPractice(other)
  await expect(box.getByText('Первая самостоятельная попытка ещё не проверена.')).toBeVisible()
  await expect(box.getByText('Ход засчитан.', { exact: true })).toBeVisible()
  await press(box.getByRole('button', { name: 'Следующий ход решения' }))
  const acceptedMove = box.locator('[data-square="e7"] [data-piece="bQ"]')
  await expect(acceptedMove).toBeVisible()

  const retry = box.getByRole('button', { name: 'Повторить проверку хода' })
  await other.route('**/api/coach/move', (route) => route.abort('failed'), { times: 1 })
  await press(retry)
  await expect(box.getByRole('alert')).toHaveText('Не удалось проверить ход. Повторите проверку.')
  await expect(acceptedMove).toBeVisible()

  const retried = other.waitForRequest('**/api/coach/move')
  await press(retry)
  expect((await retried).postDataJSON()).toMatchObject({ move: 'g8f6' })
  await expect(box.getByText('Первая самостоятельная попытка не засчитана.')).toBeVisible()
  await expect(box.getByText('Ход засчитан.', { exact: true })).toBeVisible()
  await expect(acceptedMove).toBeVisible()
  await expect(retry).toHaveCount(0)
})
