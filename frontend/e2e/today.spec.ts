import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { adminApi, userApi } from './helpers.ts'

// Each test has its own new user: the shared e2e user has activity from other specs.
test.use({ storageState: { cookies: [], origins: [] } })

let press: (l: Locator) => Promise<void>
let api: APIRequestContext
let admin: APIRequestContext

test.beforeEach(async ({ page, playwright, baseURL, hasTouch }) => {
  press = (l) => (hasTouch ? l.tap() : l.click())
  admin = await adminApi(playwright.request, baseURL!)
  const user = await userApi(playwright.request, baseURL!, admin, 'today')
  api = user.ctx
  await page.context().addCookies((await api.storageState()).cookies)
})
test.afterEach(async () => {
  await api.dispose()
  await admin.dispose()
})

const task = (page: Page, kind: string) => page.getByTestId(`task-${kind}`)

test('week block and the goal choice', async ({ page }) => {
  await page.goto('/')
  const week = page.getByRole('region', { name: 'Неделя' })
  // No zero on the screen before the first active day, and no «only started»: it is false late in the week.
  await expect(week).toContainText('Цель недели — 3 дня')
  await expect(week).not.toContainText('Неделя только началась')
  await expect(week).not.toContainText('0 из')
  await expect(week.getByRole('listitem')).toHaveCount(7)
  await expect(week.getByRole('listitem', { name: /сегодня/ })).toHaveCount(1)
  await press(week.getByRole('group', { name: 'Цель недели' }).getByRole('button', { name: '4' }))
  await expect(week).toContainText('Цель недели — 4 дня')
  await page.reload()
  await expect(week).toContainText('Цель недели — 4 дня')
})

test('a puzzle attempt counts in the puzzles task and in the week', async ({ page }) => {
  const pz = (await (await api.get('/api/puzzles/next')).json()) as { id: string }
  expect((await api.post(`/api/puzzles/${pz.id}/attempt`, { data: { solved: true, used_hint: false } })).ok()).toBe(true)
  await page.goto('/')
  await expect(task(page, 'puzzles').getByTestId('task-progress')).toHaveText('1/5')
  await expect(page.getByRole('region', { name: 'Неделя' })).toContainText('На этой неделе: 1 из 3 дней')
  await expect(page.getByRole('listitem', { name: /сегодня: занимались/ })).toHaveCount(1)
})

test('one task can be swapped, and the swap stays after reload', async ({ page }) => {
  // A due deck card adds the cards task: then the game is the spare.
  const card = { source: 'play', fen: '4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1', best_uci: 'd1d5', classification: 'blunder' }
  expect((await api.post('/api/mistakes', { data: card })).ok()).toBe(true)
  await page.goto('/')
  await expect(task(page, 'cards')).toContainText('0/1')
  await expect(task(page, 'lesson')).toBeVisible()
  await expect(task(page, 'game')).toHaveCount(0)
  await press(task(page, 'lesson').getByRole('button', { name: 'Заменить' }))
  await expect(task(page, 'game')).toContainText('Сыграть партию')
  await expect(task(page, 'lesson')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Заменить' })).toHaveCount(0)
  await page.reload()
  await expect(task(page, 'game')).toBeVisible()
  await expect(task(page, 'lesson')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Заменить' })).toHaveCount(0)
})

test('«Одна задача» opens a puzzle', async ({ page }) => {
  await page.goto('/')
  const next = page.waitForResponse((r) => r.url().includes('/api/puzzles/next'))
  await press(page.getByRole('link', { name: 'Одна задача' }))
  await expect(page.getByRole('heading', { level: 1, name: 'Задачи' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('one')).toBe('1')
  expect((await next).ok()).toBe(true)
  await expect(page.getByTestId('status')).toContainText('Ваш ход', { timeout: 10_000 })
})

test('Today fits the iPhone screen and the touch targets are large', async ({ page }, info) => {
  test.skip(info.project.name !== 'iphone', 'iPhone layout')
  const card = { source: 'play', fen: '4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1', best_uci: 'd1d5', classification: 'blunder' }
  expect((await api.post('/api/mistakes', { data: card })).ok()).toBe(true)
  await page.goto('/')
  await expect(task(page, 'lesson')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  const targets = [
    page.getByRole('link', { name: 'Одна задача' }),
    ...['3', '4', '5'].map((n) => page.getByRole('group', { name: 'Цель недели' }).getByRole('button', { name: n })),
    page.getByRole('button', { name: 'Заменить' }).first(),
    task(page, 'puzzles').getByRole('link'),
  ]
  for (const t of targets) {
    const box = (await t.boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(44)
    expect(box.height).toBeGreaterThanOrEqual(44)
  }
})

// A stubbed /api/activity: the API cannot make old activity (comeback) or a done task without real play.
const activity = (today: Partial<Record<'puzzles' | 'cards' | 'lesson_positions' | 'games', number>>, comeback = false) => ({
  date: '2026-10-21',
  today: { puzzles: 0, cards: 0, lesson_positions: 0, games: 0, ...today },
  week: { start: '2026-10-19', goal: 3, days: [true, false, false, false, false, false, false], active_days: 1, met: false, streak_weeks: 0 },
  comeback,
})
const ACTIVITY = /\/api\/activity\?/

test('the comeback card shows after a pause when nothing is done today', async ({ page }) => {
  await page.route(ACTIVITY, (r) => r.fulfill({ json: activity({}, true) }))
  await page.goto('/')
  const card = page.getByRole('region', { name: 'С возвращением' })
  await expect(card).toContainText('С возвращением!')
  // The card has the only «Одна задача» link on the page.
  await expect(page.getByRole('link', { name: 'Одна задача' })).toHaveCount(1)
  await press(card.getByRole('link', { name: 'Одна задача' }))
  await expect(page.getByRole('heading', { level: 1, name: 'Задачи' })).toBeVisible()
})

test('the tasks show when /api/activity fails', async ({ page }) => {
  await page.route(ACTIVITY, (r) => r.abort())
  await page.goto('/')
  await expect(task(page, 'puzzles').getByTestId('task-progress')).toHaveText('0/5')
  await expect(task(page, 'game')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Неделя' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Заменить' })).toHaveCount(0)
})

test('a done task has the check mark', async ({ page }) => {
  await page.route(ACTIVITY, (r) => r.fulfill({ json: activity({ puzzles: 5, games: 1 }) }))
  await page.goto('/')
  await expect(task(page, 'puzzles').getByLabel('выполнено')).toBeVisible()
  await expect(task(page, 'game').getByLabel('выполнено')).toBeVisible()
  await expect(task(page, 'lesson').getByLabel('выполнено')).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'С возвращением' })).toHaveCount(0)
})

test('a nearest achievement with target 1 has no bar and no numbers; with target > 1 it has both', async ({ page }) => {
  const next = [
    { key: 'one', title: 'Первая партия', text: 'Сыграйте партию', progress: 0, target: 1 },
    { key: 'many', title: 'Десять задач', text: 'Решите 10 задач', progress: 4, target: 10, unit: 'задач' },
  ]
  await page.route(ACTIVITY, (r) => r.fulfill({ json: { ...activity({}), achievements: { new: [], next } } }))
  await page.goto('/')
  const items = page.getByRole('region', { name: 'Ближайшие достижения' }).getByRole('listitem')
  await expect(items).toHaveCount(2)
  await expect(items.nth(0)).toHaveText('Первая партияСыграйте партию')
  await expect(items.nth(0).getByRole('progressbar')).toHaveCount(0)
  await expect(items.nth(1).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '4')
  await expect(items.nth(1)).toContainText('4 из 10 задач')
})

test('the blocks go in the order: subtitle, «Одна задача», tasks, week, plan, achievements', async ({ page }) => {
  await page.goto('/')
  const main = page.getByRole('main')
  const blocks = [
    main.getByText('Хватит и 5 минут: начните с одной задачи.'),
    main.getByRole('link', { name: 'Одна задача' }),
    main.getByRole('region', { name: 'Задания дня' }),
    main.getByRole('region', { name: 'Неделя' }),
    main.getByText('Подключите старшего тренера'),
    main.getByRole('region', { name: 'Ближайшие достижения' }),
  ]
  for (const b of blocks) await expect(b).toBeVisible({ timeout: 15_000 })
  const ys = await Promise.all(blocks.map(async (b) => (await b.boundingBox())!.y))
  expect(ys).toEqual([...ys].sort((a, b) => a - b))
  // The server line is in «Настройки» now.
  await expect(main.getByText('Сервер:')).toHaveCount(0)
})

test('the week streak agrees the word with the number', async ({ page }) => {
  const a = activity({ puzzles: 1 })
  await page.route(ACTIVITY, (r) => r.fulfill({ json: { ...a, week: { ...a.week, streak_weeks: 2 } } }))
  await page.goto('/')
  await expect(page.getByRole('region', { name: 'Неделя' })).toContainText('Цель выполнена 2 недели подряд')
})
