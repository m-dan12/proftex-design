import { defineConfig } from '@playwright/test'

import { ADMIN_PASSWORD, PORT } from './constants'

// Chromium из окружения, если он стоит не там, где ждёт Playwright.
const executablePath = process.env.PW_CHROMIUM_PATH || undefined

export default defineConfig({
  testDir: './tests',
  // Один процесс бэкенда с общей базой: сценарии идут по очереди, у каждого свои пользователи.
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    launchOptions: { executablePath },
  },
  webServer: {
    // Свежая база на каждый запуск; бэкенд отдаёт собранный frontend/dist, режим заглушки.
    command: `sh -c "rm -rf .data && cd ../backend && python3 -m uvicorn app.main:app --workers 1 --host 127.0.0.1 --port ${PORT}"`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      DATA_DIR: new URL('./.data', import.meta.url).pathname,
      FRONTEND_DIST: new URL('../frontend/dist', import.meta.url).pathname,
      SECRET_KEY: 'e2e-secret-key',
      ADMIN_USERNAME: 'admin',
      ADMIN_PASSWORD,
      COOKIE_SECURE: '0',
      // Адрес клиента берётся из X-Forwarded-For, чтобы сценарии не делили лимит попыток входа.
      TRUSTED_PROXIES: '127.0.0.0/8',
      OPENAI_API_KEY: '',
    },
  },
})
