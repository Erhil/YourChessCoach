import { expect, test } from '@playwright/test'

test('a committed puzzle result survives response loss, navigation and reload', async ({ page, hasTouch }) => {
  let committed: unknown
  const ids: string[] = []
  let offline = true
  await page.route('**/api/puzzles/*/attempt', async (route) => {
    ids.push(route.request().postDataJSON().client_id as string)
    if (committed === undefined) {
      // The real server commits. Only its response is lost.
      const response = await route.fetch()
      expect(response.status()).toBe(200)
      committed = await response.json()
      await route.abort('failed')
    } else if (offline) {
      await route.abort('failed')
    } else {
      const response = await route.fetch()
      expect(await response.json()).toEqual(committed)
      await route.fulfill({ response })
    }
  })
  const puzzleResponse = page.waitForResponse((r) => r.url().includes('/api/puzzles/next'))
  await page.goto('/puzzles')
  const puzzle = await (await puzzleResponse).json() as { solution: string[] }
  const press = async (selector: string) => {
    const element = page.locator(selector)
    if (hasTouch) await element.tap()
    else await element.click()
  }
  for (let i = 0; i < puzzle.solution.length; i += 2) {
    await expect(page.getByTestId('status')).toContainText('Ваш ход')
    const uci = puzzle.solution[i]
    await press(`[data-square="${uci.slice(0, 2)}"]`)
    await press(`[data-square="${uci.slice(2, 4)}"]`)
    if (uci.length === 5) await press(`[data-promotion="${uci[4]}"]`)
  }
  await expect(page.getByTestId('puzzle-save-status')).toContainText('Не удалось сохранить')
  await expect(page.getByTestId('rating-change')).toHaveCount(0)
  await page.goto('/profile')
  await expect(page.getByTestId('puzzle-save-status')).toContainText('Осталось: 1')
  offline = false
  await page.reload()
  await expect.poll(() => ids.length).toBeGreaterThanOrEqual(2)
  await expect(page.getByTestId('puzzle-save-status')).toHaveCount(0)
  expect(new Set(ids).size).toBe(1)
})
