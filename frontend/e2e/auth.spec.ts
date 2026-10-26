import { expect, test, type Locator, type Page } from '@playwright/test'
import { ADMIN_TOKEN } from './constants.ts'
import { adminApi, createUser, uniqueLogin, userApi } from './helpers.ts'

// Every test here starts without a session.
test.use({ storageState: { cookies: [], origins: [] } })

test.describe('login and admin', () => {
  let press: (l: Locator) => Promise<void>
  test.beforeEach(({ hasTouch }) => {
    press = (l) => (hasTouch ? l.tap() : l.click())
  })

  const logIn = async (page: Page, login: string, token: string) => {
    await page.getByLabel('Логин').fill(login)
    await page.getByLabel('Токен').fill(token)
    await press(page.getByRole('button', { name: 'Войти' }))
  }

  test('login page, wrong token, right token, logout, return to the same page', async ({ page, playwright, baseURL }) => {
    const admin = await adminApi(playwright.request, baseURL!)
    const user = await createUser(admin, uniqueLogin('auth'))
    await page.goto('/profile')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Вход' })).toBeVisible()
    await expect(page.getByLabel('Токен')).toHaveAttribute('type', 'password')

    await logIn(page, user.login, 'aaaa-bbbb-cccc-dddd')
    await expect(page.getByRole('alert')).toHaveText('Неверный логин или токен')

    await logIn(page, user.login, user.token)
    await expect(page).toHaveURL(/\/profile$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Профиль' })).toBeVisible()

    const menu = page.getByRole('button', { name: 'Меню' })
    if (await menu.isVisible()) await press(menu)
    await expect(page.getByRole('navigation', { name: 'Разделы' })).toContainText(user.login)
    await press(page.getByRole('button', { name: 'Выйти', exact: true }))
    await expect(page.getByRole('heading', { level: 1, name: 'Вход' })).toBeVisible()
    await page.goto('/')
    await expect(page).toHaveURL(/\/login$/)
    await admin.dispose()
  })

  test('admin: wrong token, create user, reset token', async ({ page, playwright, baseURL }) => {
    await page.goto('/admin')
    await page.getByLabel('Токен администратора').fill('wrong-token')
    await press(page.getByRole('button', { name: 'Войти' }))
    await expect(page.getByRole('alert')).toBeVisible()

    await page.getByLabel('Токен администратора').fill(ADMIN_TOKEN)
    await press(page.getByRole('button', { name: 'Войти' }))
    await expect(page.getByRole('button', { name: 'Выйти из админки' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

    const login = uniqueLogin('adm')
    await page.getByLabel('Логин нового пользователя').fill(login)
    await press(page.getByRole('button', { name: 'Создать пользователя' }))
    await expect(page.getByText('Токен показывается один раз')).toBeVisible()
    const first = (await page.getByTestId('token').textContent())!
    expect(first).toMatch(/^[a-z0-9]{4}(-[a-z0-9]{4}){3}$/)
    await expect(page.getByTestId(`user-${login}`)).toBeVisible()

    const api = await playwright.request.newContext({ baseURL })
    const ok = await api.post('/api/auth/login', { data: { login, token: first } })
    expect(ok.ok()).toBe(true)

    await press(page.getByTestId(`user-${login}`).getByRole('button', { name: 'Сбросить токен' }))
    await expect(page.getByText('Старый токен перестанет работать')).toBeVisible()
    await press(page.getByRole('button', { name: 'Да, сбросить' }))
    await expect(page.getByTestId('token')).not.toHaveText(first)
    const second = (await page.getByTestId('token').textContent())!

    // the old token fails, the new token works, the old session is gone
    expect((await api.post('/api/auth/login', { data: { login, token: first } })).status()).toBe(401)
    expect((await api.get('/api/auth/me')).status()).toBe(401)
    expect((await api.post('/api/auth/login', { data: { login, token: second } })).ok()).toBe(true)

    await press(page.getByTestId(`user-${login}`).getByRole('button', { name: 'Прогресс' }))
    await expect(page.getByRole('heading', { name: `Прогресс: ${login}` })).toBeVisible()
    await expect(page.getByText(/Рейтинг в задачах: \d+/)).toBeVisible()

    await press(page.getByRole('button', { name: 'Выйти из админки' }))
    await expect(page.getByLabel('Токен администратора')).toBeVisible()
    await api.dispose()
  })

  test('two users do not see each other', async ({ page, playwright, baseURL }) => {
    const admin = await adminApi(playwright.request, baseURL!)
    const a = await userApi(playwright.request, baseURL!, admin, 'usera')
    const b = await createUser(admin, uniqueLogin('userb'))
    const game = { pgn: '1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#', player_color: 'black', level: 800, result: '1-0', termination: 'checkmate' }
    expect((await a.ctx.post('/api/games', { data: game })).ok()).toBe(true)
    const card = { source: 'play', fen: '4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1', best_uci: 'd1d5', classification: 'blunder' }
    expect((await a.ctx.post('/api/mistakes', { data: card })).ok()).toBe(true)
    const own = (await (await a.ctx.get('/api/mistakes/next')).json()) as { card: unknown }
    expect(own.card).not.toBeNull()

    await page.goto('/review')
    await logIn(page, b.login, b.token)
    await expect(page.getByRole('heading', { level: 1, name: 'Разбор партии' })).toBeVisible()
    await expect(page.locator('li', { hasText: 'чёрными' })).toHaveCount(0)

    const next = (await (await page.request.get('/api/mistakes/next')).json()) as { card: unknown }
    expect(next.card).toBeNull()
    await page.goto('/mistakes')
    // User a has a card; user b sees the empty deck with 0 cards.
    await expect(page.getByTestId('status')).toHaveText('На сегодня всё повторено. Карточек в колоде: 0')
    await a.ctx.dispose()
    await admin.dispose()
  })
})
