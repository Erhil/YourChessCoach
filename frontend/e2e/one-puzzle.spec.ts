import { expect, test, type APIRequest, type Locator, type Page } from '@playwright/test'
import { Chess } from 'chess.js'
import { adminApi, userApi } from './helpers.ts'

type Puzzle = { id: string; fen: string; opponent_move: string; solution: string[] }

// Its own new user: the test makes puzzle attempts.
test.use({ storageState: { cookies: [], origins: [] } })

async function setup(page: Page, hasTouch: boolean, request: APIRequest, baseURL: string) {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const admin = await adminApi(request, baseURL)
  const { ctx } = await userApi(request, baseURL, admin, 'one')
  await page.context().addCookies((await ctx.storageState()).cookies)
  const status = page.getByTestId('status')
  const open = async (go: () => Promise<unknown>): Promise<Puzzle> => {
    const resp = page.waitForResponse((r) => r.url().includes('/api/puzzles/next'))
    await go()
    const pz = (await (await resp).json()) as Puzzle
    await expect(status).toContainText('Ваш ход', { timeout: 10_000 })
    return pz
  }
  const play = async (uci: string) => {
    await press(page.locator(`[data-square="${uci.slice(0, 2)}"]`))
    await press(page.locator(`[data-square="${uci.slice(2, 4)}"]`))
    if (uci.length === 5) await press(page.locator(`[data-promotion="${uci[4]}"]`))
  }
  const dispose = async () => {
    await ctx.dispose()
    await admin.dispose()
  }
  return { press, status, open, play, dispose }
}

test('«Одна задача» mode: after the end, «Ещё одну?» and «На сегодня хватит»', async ({ page, hasTouch, playwright, baseURL }, info) => {
  const { press, status, open, play, dispose } = await setup(page, hasTouch, playwright.request, baseURL!)
  const more = page.getByRole('button', { name: 'Ещё одну?' })
  const stop = page.getByRole('button', { name: 'На сегодня хватит' })

  const first = await open(() => page.goto('/puzzles?one=1'))
  await expect(more).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Следующая задача' })).toBeVisible()
  for (let i = 0; i < first.solution.length; i += 2) {
    await play(first.solution[i])
    if (i + 1 < first.solution.length) await expect(status).toContainText('Ваш ход', { timeout: 10_000 })
  }
  await expect(status).toHaveText('Решено!')
  await expect(page.getByRole('button', { name: 'Следующая задача' })).toHaveCount(0)
  for (const b of [more, stop]) {
    const box = (await b.boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(44)
    expect(box.height).toBeGreaterThanOrEqual(44)
  }
  if (info.project.name === 'iphone') {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }

  const second = await open(() => press(more))
  expect(second.id).not.toBe(first.id)
  await expect(more).toHaveCount(0)
  // A wrong move also ends the puzzle: both buttons show, and «На сегодня хватит» goes to «Сегодня».
  const chess = new Chess(second.fen)
  chess.move({ from: second.opponent_move.slice(0, 2), to: second.opponent_move.slice(2, 4), promotion: second.opponent_move[4] })
  const wrong = chess.moves({ verbose: true }).find((m) => m.lan !== second.solution[0] && !m.promotion && !m.san.includes('#'))!
  await play(wrong.lan)
  await expect(status).toHaveText('Неверно', { timeout: 10_000 })
  // The mode stays after «Ещё одну?»: the second end shows «Ещё одну?» again, not «Следующая задача».
  await expect(more).toBeVisible()
  await expect(page.getByRole('button', { name: 'Следующая задача' })).toHaveCount(0)
  await press(stop)
  await expect(page.getByRole('heading', { level: 1, name: 'Сегодня' })).toBeVisible()
  await dispose()
})

test('normal mode: after the end, «Следующая задача» and no «Ещё одну?» or «На сегодня хватит»', async ({ page, hasTouch, playwright, baseURL }) => {
  const { status, open, play, dispose } = await setup(page, hasTouch, playwright.request, baseURL!)
  const pz = await open(() => page.goto('/puzzles'))
  for (let i = 0; i < pz.solution.length; i += 2) {
    await play(pz.solution[i])
    if (i + 1 < pz.solution.length) await expect(status).toContainText('Ваш ход', { timeout: 10_000 })
  }
  await expect(status).toHaveText('Решено!')
  await expect(page.getByRole('button', { name: 'Следующая задача' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Ещё одну?' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'На сегодня хватит' })).toHaveCount(0)
  await dispose()
})
