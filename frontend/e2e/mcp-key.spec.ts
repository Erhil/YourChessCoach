import { expect, test, type Locator } from '@playwright/test'
import { ADMIN_TOKEN } from './constants.ts'
import { adminApi, userApi } from './helpers.ts'

test.describe('senior coach', () => {
  let press: (l: Locator) => Promise<void>
  test.beforeEach(({ hasTouch }) => {
    press = (l) => (hasTouch ? l.tap() : l.click())
  })

  // Its own new user: parallel profiles would create and delete the same key of the shared user.
  test.describe('own user', () => {
  test.use({ storageState: { cookies: [], origins: [] } })
  test('settings: create, replace and delete the MCP key', async ({ page, context, playwright, baseURL }) => {
    const admin = await adminApi(playwright.request, baseURL!)
    const user = await userApi(playwright.request, baseURL!, admin, 'mcpset')
    await context.addCookies((await user.ctx.storageState()).cookies)
    await context.grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => undefined)
    await page.goto('/settings')
    await expect(page.getByTestId('mcp-state')).toHaveText('Ключа нет')
    await press(page.getByRole('button', { name: 'Создать ключ' }))
    const first = (await page.getByTestId('token').textContent())!
    expect(first.length).toBeGreaterThan(10)
    await expect(page.getByText('Токен показывается один раз')).toBeVisible()
    await expect(page.getByTestId('mcp-state')).toContainText('Ключ создан')
    await page.getByText('Как подключить').click()
    await expect(page.getByTestId('mcp-command')).toContainText(`Bearer ${first}`)
    await expect(page.getByTestId('mcp-command')).toContainText('/mcp')
    await press(page.getByRole('button', { name: 'Скопировать', exact: true }))
    await expect(page.getByRole('region', { name: 'Старший тренер (MCP)' }).getByRole('status')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

    await press(page.getByRole('button', { name: 'Заменить ключ' }))
    await expect(page.getByText('Старый ключ перестанет работать')).toBeVisible()
    await press(page.getByRole('button', { name: 'Да, заменить' }))
    await expect(page.getByTestId('token')).not.toHaveText(first)

    await press(page.getByRole('button', { name: 'Удалить ключ' }))
    await press(page.getByRole('button', { name: 'Да, удалить' }))
    await expect(page.getByTestId('mcp-state')).toHaveText('Ключа нет')
    await expect(page.getByTestId('token')).toHaveCount(0)
    await user.ctx.dispose()
    await admin.dispose()
  })
  })

  test('today: plan block and focus theme, or the hint', async ({ page }) => {
    // Nothing done today: a done task of the shared user keeps its place and can push the puzzles task out.
    await page.route(/\/api\/activity\?/, async (r) => {
      const json = await (await r.fetch()).json()
      await r.fulfill({ json: { ...json, today: { puzzles: 0, cards: 0, lesson_positions: 0, games: 0 } } })
    })
    await page.route('**/api/plan', (r) => r.fulfill({ json: { plan: null } }))
    await page.goto('/')
    await expect(page.getByText('Подключите старшего тренера в настройках профиля')).toBeVisible()
    await expect(page.getByRole('region', { name: 'План от старшего тренера' })).toHaveCount(0)

    const themes = (await (await page.request.get('/api/puzzles/themes')).json()) as { key: string; name: string }[]
    const focus = themes[0]
    await page.unroute('**/api/plan')
    await page.route('**/api/plan', (r) =>
      r.fulfill({
        json: {
          plan: {
            created_at: '2026-10-24T10:00:00Z',
            summary: 'Первая строка плана\nВторая строка плана',
            focus_themes: [focus.key],
            lessons: [],
            openings: [],
          },
        },
      }),
    )
    await page.goto('/')
    const block = page.getByRole('region', { name: 'План от старшего тренера' })
    await expect(block).toContainText('Вторая строка плана')
    await expect(block.getByRole('link', { name: focus.name })).toHaveAttribute('href', `/puzzles?theme=${encodeURIComponent(focus.key)}`)
    await expect(page.getByRole('link', { name: new RegExp(`Задачи по теме «${focus.name}»`) })).toHaveAttribute(
      'href',
      `/puzzles?theme=${encodeURIComponent(focus.key)}`,
    )
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    // The achievement message loads /api/activity too; its routed request can still be in flight here.
    await page.unrouteAll({ behavior: 'ignoreErrors' })
  })

  // The admin cookie would replace the shared user's session, so this test starts without a session.
  test.describe('admin', () => {
  test.use({ storageState: { cookies: [], origins: [] } })
  test('key flag and revoke', async ({ page, playwright, baseURL }) => {
    const admin = await adminApi(playwright.request, baseURL!)
    const user = await userApi(playwright.request, baseURL!, admin, 'mcpk')
    expect((await user.ctx.post('/api/mcp-key', { data: {} })).ok()).toBe(true)

    await page.goto('/admin')
    await page.getByLabel('Токен администратора').fill(ADMIN_TOKEN)
    await press(page.getByRole('button', { name: 'Войти' }))
    const row = page.getByTestId(`user-${user.login}`)
    await expect(row.locator('td[data-label="Ключ MCP"]')).toHaveText('есть')
    await press(row.getByRole('button', { name: 'Отозвать ключ' }))
    await press(page.getByRole('button', { name: 'Да, отозвать' }))
    await expect(row.locator('td[data-label="Ключ MCP"]')).toHaveText('нет')
    await expect(row.getByRole('button', { name: 'Отозвать ключ' })).toHaveCount(0)
    await user.ctx.dispose()
    await admin.dispose()
  })
  })
})
