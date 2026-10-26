import { request, type FullConfig } from '@playwright/test'
import { STORAGE_STATE } from './constants.ts'
import { adminApi, userApi } from './helpers.ts'

// One test user per run. Its session goes to a file that every project uses as storageState.
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL!
  const admin = await adminApi(request, baseURL)
  const user = await userApi(request, baseURL, admin, 'e2e')
  await user.ctx.storageState({ path: STORAGE_STATE(process.env.E2E_DB_NAME!) })
  await user.ctx.dispose()
  await admin.dispose()
}
