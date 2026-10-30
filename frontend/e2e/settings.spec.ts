import { expect, test } from '@playwright/test'

test('Settings reports a missing selected model and backup errors', async ({ page, hasTouch }) => {
  await page.route('**/api/health', route => route.fulfill({ json: {
    status: 'ok', version: 'test', engines: { stockfish: { available: true } },
    llm: { enabled: true, available: false, reachable: true, model_present: false,
      model: 'missing:4b', status: 'model_missing' },
    backup: { error: 'test disk error' },
  } }))
  await page.goto('/profile')
  const settings = page.getByRole('region', { name: 'Настройки', exact: true })
  await expect(settings).toContainText('модель missing:4b не установлена')
  await expect(settings).toContainText('Резервная копия: ошибка сохранения')
  const light = settings.getByLabel('Светлая', { exact: true })
  await (hasTouch ? light.tap() : light.click())
  await expect(light).toBeChecked()
})


test('Settings does not promise scheduled backups without health data', async ({ page }) => {
  await page.route('**/api/health', route => route.abort())
  await page.goto('/profile')
  const settings = page.getByRole('region', { name: 'Настройки', exact: true })
  await expect(settings).toContainText('Сервер: нет связи')
  await expect(settings).toContainText('Резервная копия: статус неизвестен')
  await expect(settings).not.toContainText('Резервная копия: по расписанию')
})
