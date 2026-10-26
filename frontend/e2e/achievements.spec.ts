import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { adminApi, userApi } from './helpers.ts'

// Each test has its own new user: the shared e2e user has achievements from other specs.
test.use({ storageState: { cookies: [], origins: [] } })

let press: (l: Locator) => Promise<void>
let api: APIRequestContext
let admin: APIRequestContext

test.beforeEach(async ({ page, playwright, baseURL, hasTouch }) => {
  press = (l) => (hasTouch ? l.tap() : l.click())
  admin = await adminApi(playwright.request, baseURL!)
  const user = await userApi(playwright.request, baseURL!, admin, 'award')
  api = user.ctx
  await page.context().addCookies((await api.storageState()).cookies)
})
test.afterEach(async () => {
  await api.dispose()
  await admin.dispose()
})

async function solveOne() {
  const pz = (await (await api.get('/api/puzzles/next')).json()) as { id: string }
  expect((await api.post(`/api/puzzles/${pz.id}/attempt`, { data: { solved: true, used_hint: false } })).ok()).toBe(true)
}
const note = (page: Page) => page.getByRole('status').filter({ hasText: 'Достижение' })
const animation = (l: Locator) => l.evaluate((e) => getComputedStyle(e).animationName)

test('the first solved puzzle gives one message, and «Сегодня» shows the nearest achievements', async ({ page }, info) => {
  await solveOne()
  const seen = page.waitForResponse((r) => r.url().includes('/api/achievements/seen'))
  await page.goto('/')
  await expect(note(page)).toContainText('Достижение: Первая задача')
  expect((await seen).status()).toBe(204)
  expect(await animation(note(page))).toBe('pop')
  if (info.project.name === 'iphone') {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  // Measure after the scale animation ends.
  await note(page).evaluate((e) => Promise.all(e.getAnimations().map((a) => a.finished)))
  const close = note(page).getByRole('button', { name: 'Закрыть' })
  const box = (await close.boundingBox())!
  expect(box.width).toBeGreaterThanOrEqual(44)
  expect(box.height).toBeGreaterThanOrEqual(44)

  const next = page.getByRole('region', { name: 'Ближайшие достижения' })
  const bars = next.getByRole('progressbar')
  // count() does not wait: wait until the activity has loaded.
  await expect(bars.first()).toBeVisible()
  expect(await bars.count()).toBeGreaterThan(0)
  expect(await bars.count()).toBeLessThanOrEqual(3)
  await expect(bars.first()).toHaveAttribute('aria-valuemax', /\d+/)
  await expect(next).toContainText(/\d+ из \d+ \S+/)

  await press(close)
  await expect(note(page)).toHaveCount(0)
  await page.reload()
  await expect(next).toBeVisible()
  await page.waitForLoadState('networkidle')
  await expect(note(page)).toHaveCount(0)
})

test('a puzzle solved on the board shows the message on the puzzles page', async ({ page }) => {
  const resp = page.waitForResponse((r) => r.url().includes('/api/puzzles/next'))
  await page.goto('/puzzles')
  const pz = (await (await resp).json()) as { solution: string[] }
  const status = page.getByTestId('status')
  await expect(status).toContainText('Ваш ход', { timeout: 10_000 })
  for (let i = 0; i < pz.solution.length; i += 2) {
    const uci = pz.solution[i]
    await press(page.locator(`[data-square="${uci.slice(0, 2)}"]`))
    await press(page.locator(`[data-square="${uci.slice(2, 4)}"]`))
    if (uci.length === 5) await press(page.locator(`[data-promotion="${uci[4]}"]`))
    if (i + 1 < pz.solution.length) {
      await expect(status).toContainText('Соперник ходит')
      await expect(status).toContainText('Ваш ход', { timeout: 10_000 })
    }
  }
  await expect(status).toHaveText('Решено!')
  await expect(note(page)).toContainText('Достижение: Первая задача')
})

test('no animation with «reduce motion»', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await solveOne()
  await page.goto('/')
  await expect(note(page)).toBeVisible()
  expect(await animation(note(page))).toBe('none')
})

test('the «Анимация наград» switch stays off after reload and turns the animation off', async ({ page }) => {
  await page.goto('/settings')
  const sw = page.getByLabel('Анимация наград')
  await expect(sw).toBeChecked()
  await press(sw)
  await expect(sw).not.toBeChecked()
  await page.reload()
  await expect(sw).not.toBeChecked()
  await solveOne()
  await page.goto('/')
  await expect(note(page)).toBeVisible()
  expect(await animation(note(page))).toBe('none')
})

test('a done task check mark animates once on this day', async ({ page }) => {
  // Five puzzle requests: with all profiles in parallel they can take more than the default 30 s.
  test.slow()
  for (let i = 0; i < 5; i++) await solveOne()
  await page.goto('/')
  const mark = page.getByTestId('task-puzzles').getByLabel('выполнено')
  await expect(mark).toBeVisible()
  expect(await animation(mark)).toBe('pop')
  await page.reload()
  await expect(mark).toBeVisible()
  expect(await animation(mark)).toBe('none')
})
