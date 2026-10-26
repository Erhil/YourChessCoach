import { expect, test, type Locator } from '@playwright/test'

const pages = [
  'Сегодня', 'Игра', 'Задачи', 'Уроки', 'Разбор партии',
  'Колода ошибок', 'Профиль',
]

test('every section opens', async ({ page, hasTouch }) => {
  const press = (l: Locator) => (hasTouch ? l.tap() : l.click())
  const menu = page.getByRole('button', { name: 'Меню' })

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Сегодня' })).toBeVisible()

  for (const name of pages) {
    if (await menu.isVisible()) await press(menu)
    await press(page.getByRole('navigation', { name: 'Разделы' }).getByRole('link', { name, exact: true }))
    await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  }
  // The last section is «Профиль»: its «Настройки» part has the server line.
  await expect(page.getByText('Сервер: работает. Stockfish: найден')).toBeVisible()
})

test('iPhone: no horizontal scroll, menu button is touch sized', async ({ page }, info) => {
  test.skip(info.project.name !== 'iphone')
  await page.goto('/')
  await expect(page.getByRole('region', { name: 'Задания дня' })).toBeVisible({ timeout: 15_000 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
  expect(overflow).toBe(true)
  const box = await page.getByRole('button', { name: 'Меню' }).boundingBox()
  expect(box!.width).toBeGreaterThanOrEqual(44)
  expect(box!.height).toBeGreaterThanOrEqual(44)
})

test('wide screen: the nav column stays in view while the page scrolls', async ({ page }, info) => {
  test.skip(info.project.name === 'iphone' || info.project.name === 'ipad')
  await page.goto('/review')
  await expect(page.locator('main')).toBeVisible()
  await page.evaluate(() => {
    document.querySelector('main')!.style.minHeight = '3000px'
    window.scrollTo(0, 500)
  })
  const box = (await page.getByRole('navigation', { name: 'Разделы' }).boundingBox())!
  expect(box.y).toBe(0)
})
