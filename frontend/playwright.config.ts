import { defineConfig, devices } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { ADMIN_TOKEN, STORAGE_STATE } from './e2e/constants.ts'

const root = path.resolve(import.meta.dirname, '..')
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const port = 6356
// Each run has its own database file, so parallel runs do not delete each other's data.
// The main process picks the name once; workers get it through the environment.
process.env.E2E_DB_NAME ??= `e2e-${Date.now()}-${process.pid}.db`
const e2eDb = path.join(import.meta.dirname, 'test-results', process.env.E2E_DB_NAME)
// Only the main process deletes the file, and only this run's file.
if (process.env.TEST_WORKER_INDEX === undefined) {
  for (const suffix of ['', '-wal', '-shm']) fs.rmSync(e2eDb + suffix, { force: true })
}

// Touch profiles run in WebKit (as Safari); E2E_TOUCH_BROWSER=chromium switches them to Chromium.
const touch = (device: string) => {
  const d = devices[device]
  return process.env.E2E_TOUCH_BROWSER === 'chromium' ? { ...d, defaultBrowserType: 'chromium' as const } : d
}

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results/artifacts',
  reporter: [['list']],
  globalSetup: './e2e/global-setup.ts',
  // One test server for all browsers: with the default (12 on the dev machine) it answers slower
  // than the 5 s waits of the specs, and tests fail at random. 6 workers: no such failures.
  workers: 6,
  use: { baseURL: `http://127.0.0.1:${port}`, storageState: STORAGE_STATE(process.env.E2E_DB_NAME) },
  webServer: {
    command: `"${python}" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port ${port}`,
    cwd: root,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    env: {
      APP_PORT: String(port),
      APP_DB_PATH: e2eDb,
      LLM_ENABLED: 'false',
      ADMIN_TOKEN,
      // All parallel workers share one test user; the per-user limit is tested in test_security.py.
      ENGINE_REQUESTS_PER_USER: '1000',
      FRONTEND_DIST: path.join(import.meta.dirname, 'dist'),
    },
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'iphone', use: touch('iPhone 13 Mini') },
    { name: 'ipad', use: touch('iPad (gen 11)') },
    { name: 'ipad-landscape', use: touch('iPad (gen 11) landscape') },
  ],
})
