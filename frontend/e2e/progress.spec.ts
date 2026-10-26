import { expect, test, type Locator } from '@playwright/test'
import { adminApi, userApi } from './helpers.ts'

// Its own new user: done tasks of the shared user can push the puzzles task out of the three tasks.
test.describe('own user', () => {
test.use({ storageState: { cookies: [], origins: [] } })
test('Today: plan and puzzle step', async ({ page, hasTouch, playwright, baseURL }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const admin = await adminApi(playwright.request, baseURL!)
  const user = await userApi(playwright.request, baseURL!, admin, 'today-plan')
  await page.context().addCookies((await user.ctx.storageState()).cookies)
  await page.goto('/')
  // The game is the spare task when deck cards are due, so the test checks the tasks block.
  // /api/activity can take more than 5 s while all profiles run in parallel.
  await expect(page.getByRole('region', { name: 'Задания дня' })).toBeVisible({ timeout: 15_000 })
  // The plan step, not the navigation link "Задачи".
  await press(page.getByRole('main').getByRole('link', { name: /5 задач/ }))
  await expect(page.getByRole('heading', { level: 1, name: 'Задачи' })).toBeVisible()
  await user.ctx.dispose()
  await admin.dispose()
})

// Its own new user: done puzzles of the shared user can push the puzzles task out of the three tasks,
// and the shared user can have a plan focus theme or a weaker theme from other specs.
test('Today links to the weak theme in Puzzles', async ({ page, hasTouch, playwright, baseURL }) => {
  const admin = await adminApi(playwright.request, baseURL!)
  const { ctx: request } = await userApi(playwright.request, baseURL!, admin, 'weak')
  await page.context().addCookies((await request.storageState()).cookies)
  // A weak theme needs at least 3 attempts in one theme: make them here, do not rely on other tests.
  for (let i = 0; i < 3; i++) {
    const pz = (await (await request.get('/api/puzzles/next?theme=fork')).json()) as { id: string }
    await request.post(`/api/puzzles/${pz.id}/attempt`, { data: { solved: false, used_hint: false } })
  }
  await page.goto('/')
  const link = page.getByRole('link', { name: /Задачи по теме/ })
  await expect(link).toBeVisible()
  await (hasTouch ? link.tap() : link.click())
  await expect(page).toHaveURL(/\/puzzles\?theme=/)
  const theme = new URL(page.url()).searchParams.get('theme')!
  await expect(page.getByLabel('Тема')).toHaveValue(theme)
  await request.dispose()
  await admin.dispose()
})
})

test('Profile shows the themes after an attempt', async ({ page, request }, info) => {
  await page.goto('/profile')
  await expect(page.getByRole('group', { name: 'Рейтинг в задачах' })).toContainText(/Рейтинг в задачах\s*\d+/)

  const pz = (await (await request.get('/api/puzzles/next')).json()) as { id: string }
  const r = await request.post(`/api/puzzles/${pz.id}/attempt`, { data: { solved: true, used_hint: false } })
  expect(r.ok()).toBe(true)

  await page.goto('/profile')
  await expect(page.getByRole('heading', { name: 'Темы' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Попыток' })).toBeVisible()
  await expect(page.getByText(/Уроки: \d+ из \d+ пройдено/)).toBeVisible()
  if (info.project.name === 'iphone') {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

// Its own new user: the test checks 1 active day and the first achievement.
test.describe('own user', () => {
  test.use({ storageState: { cookies: [], origins: [] } })
  test('Profile: calendar, weeks and earned achievements after a puzzle', async ({ page, playwright, baseURL }, info) => {
    const admin = await adminApi(playwright.request, baseURL!)
    const { ctx: api } = await userApi(playwright.request, baseURL!, admin, 'progress')
    await page.context().addCookies((await api.storageState()).cookies)
    const pz = (await (await api.get('/api/puzzles/next')).json()) as { id: string }
    expect((await api.post(`/api/puzzles/${pz.id}/attempt`, { data: { solved: true, used_hint: false } })).ok()).toBe(true)

    await page.goto('/profile')
    const calendar = page.getByRole('group', { name: 'Календарь' })
    await expect(calendar).toContainText('1 активный день за 12 недель')
    await expect(calendar.getByRole('img', { name: 'Активных дней за 12 недель: 1' })).toBeVisible()
    await expect(calendar.locator('[data-active]')).toHaveCount(1)
    const weeks = page.getByRole('region', { name: 'Последние недели' })
    // Only the week with activity: no list of zero weeks.
    await expect(weeks.getByTestId('week')).toHaveCount(1)
    await expect(weeks.getByTestId('week').first()).toContainText('задач решено: 1')
    await expect(weeks.getByTestId('week').first()).toContainText('зевки на 10 ходов: —')
    await expect(page.getByRole('region', { name: 'Достижения', exact: true })).toContainText('Первая задача')
    if (info.project.name === 'iphone') {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    }
    await api.dispose()
    await admin.dispose()
  })

  test('Profile hides the weeks block without activity', async ({ page, playwright, baseURL }) => {
    const admin = await adminApi(playwright.request, baseURL!)
    const { ctx: api } = await userApi(playwright.request, baseURL!, admin, 'noweeks')
    await page.context().addCookies((await api.storageState()).cookies)
    await page.goto('/profile')
    await expect(page.getByRole('group', { name: 'Календарь' })).toContainText('0 активных дней за 12 недель')
    await expect(page.getByRole('region', { name: 'Последние недели' })).toHaveCount(0)
    await expect(page.getByText('В колоде: 0 карточек, усвоено: 0')).toBeVisible()
    await api.dispose()
    await admin.dispose()
  })
})
