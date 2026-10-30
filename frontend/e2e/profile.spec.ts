import { expect, test } from '@playwright/test'
import { adminApi, userApi } from './helpers.ts'

const START_RATING = 600
const signed = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : '0')
const dayMonth = (d: Date) => `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`

// Its own new user: the test checks the numbers after exactly one puzzle attempt.
test.describe('own user', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('Profile: summary tiles after one puzzle, settings, old addresses', async ({ page, playwright, baseURL }, info) => {
    const admin = await adminApi(playwright.request, baseURL!)
    const { ctx: api } = await userApi(playwright.request, baseURL!, admin, 'profile')
    await page.context().addCookies((await api.storageState()).cookies)
    const pz = (await (await api.get('/api/puzzles/next')).json()) as { id: string }
    expect((await api.post(`/api/puzzles/${pz.id}/attempt`, { data: { solved: true, used_hint: false } })).ok()).toBe(true)
    const p = (await (await api.get('/api/progress')).json()) as {
      puzzles: { rating: number }
      themes: { name: string; rating: number }[]
      lessons: { total: number }
    }
    const goal = ((await (await api.get('/api/activity')).json()) as { week: { goal: number } }).week.goal
    const catalogue = ((await (await api.get('/api/achievements')).json()) as { total: number }).total

    await page.goto('/profile')
    await expect(page.getByRole('heading', { level: 1, name: 'Профиль' })).toBeVisible()
    const summary = page.getByRole('region', { name: 'Сводка' })
    const tile = (name: string) => summary.getByRole('group', { name, exact: true })
    await expect(summary.getByTestId('tile')).toHaveCount(9)
    const rating = tile('Рейтинг в задачах')
    await expect(rating).toContainText(String(p.puzzles.rating))
    await expect(rating.getByTestId('change')).toHaveText(`${signed(p.puzzles.rating - START_RATING)} с первой задачи`)
    await expect(rating.getByRole('img')).toHaveAttribute('aria-label', new RegExp(`сейчас ${p.puzzles.rating}$`))
    await expect(tile('Неделя')).toContainText(`1 из ${goal} дней`)
    await expect(tile('Зевки на 10 ходов')).toContainText('—')
    await expect(tile('Зевки на 10 ходов')).toContainText('Сохраните и разберите партию, чтобы увидеть')
    await expect(tile('Партии')).toContainText('0 побед · 0 ничьих · 0 поражений')
    await expect(tile('Партии')).not.toContainText('тренировочных')
    // The random puzzle can have no theme of the offered list: then the tile says so.
    if (p.themes.length === 0) {
      await expect(tile('Темы')).toContainText('Решите задачи, чтобы увидеть темы')
    } else {
      const best = [...p.themes].sort((a, b) => b.rating - a.rating)[0]
      await expect(tile('Темы').getByRole('listitem').first()).toHaveText(`${best.name} ${best.rating}`)
      await expect(tile('Темы').getByRole('listitem')).toHaveCount(Math.min(4, p.themes.length))
      await expect(tile('Темы')).not.toContainText('Сильные')
      await expect(tile('Темы')).toContainText('По первым попыткам')
    }
    await expect(tile('Колода')).toContainText('0 на сегодня')
    await expect(tile('Колода')).toContainText('усвоено 0 из 0')
    await expect(tile('Уроки')).toContainText(`0 из ${p.lessons.total}`)
    await expect(tile('Достижения')).toContainText(`1 из ${catalogue}`)
    await expect(tile('Достижения')).toContainText('Последнее: Первая задача')
    const calendar = tile('Календарь')
    await expect(calendar).toContainText('1 активный день за 12 недель')
    // The day cells are too small to tap: they are not interactive, the label gives the dates.
    await expect(calendar.getByRole('img')).toHaveAttribute('aria-label', `Активных дней за 12 недель: 1. Дни: ${dayMonth(new Date())} (сегодня)`)
    await expect(calendar.locator('[data-active]')).toHaveCount(1)
    await expect(calendar.locator('[tabindex], button')).toHaveCount(0)
    await expect(calendar).not.toContainText('Коснитесь')
    // 12 cells in every layout: no row of the grid has an empty cell.
    const boxes = await Promise.all((await summary.getByTestId('tile').all()).map((t) => t.boundingBox()))
    const width = (await summary.boundingBox())!.width
    const rows = new Map<number, number>()
    for (const b of boxes) rows.set(Math.round(b!.y), (rows.get(Math.round(b!.y)) ?? 0) + b!.width)
    for (const w of rows.values()) expect(w).toBeGreaterThan(width - 40)

    if (info.project.name === 'ipad') {
      await page.evaluate(() => window.scrollTo(0, 0))
      for (const box of await Promise.all((await summary.getByTestId('tile').all()).map((t) => t.boundingBox())))
        expect(box!.y + box!.height).toBeLessThanOrEqual(944)
    }
    if (info.project.name === 'iphone') {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      const box = (await rating.boundingBox())!
      expect(box.y + box.height).toBeLessThanOrEqual(629)
    }

    const settings = page.getByRole('region', { name: 'Настройки' })
    await expect(settings.getByRole('heading', { level: 2, name: 'Настройки' })).toBeVisible()
    await expect(settings.getByLabel('Помощь тренера')).toBeVisible()
    await expect(settings.getByLabel('Анимация наград')).toBeVisible()
    await expect(settings.getByText('Сервер: работает')).toBeVisible()

    await page.goto('/progress')
    await expect(page).toHaveURL(/\/profile$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Профиль' })).toBeVisible()
    await page.goto('/settings')
    await expect(page).toHaveURL(/\/profile#settings$/)
    await expect(settings.getByRole('heading', { level: 2, name: 'Настройки' })).toBeInViewport()
    await api.dispose()
    await admin.dispose()
  })
})

test('Profile: a tile whose request failed shows «нет данных»', async ({ page }) => {
  await page.route('**/api/achievements?**', (r) => r.abort())
  await page.route('**/api/mistakes/next?**', (r) => r.abort())
  await page.goto('/profile')
  const tile = (name: string) => page.getByRole('region', { name: 'Сводка' }).getByRole('group', { name, exact: true })
  await expect(tile('Достижения')).toContainText('нет данных')
  await expect(tile('Колода')).toContainText('нет данных')
  await expect(tile('Неделя')).not.toContainText('нет данных')
  await expect(tile('Неделя')).not.toContainText('…')
})
