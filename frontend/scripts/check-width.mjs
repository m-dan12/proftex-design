// Показатель 6 карточки T03 (и часть S-15): на ширине 360 px у экранов входа и layout
// нет горизонтальной прокрутки и нет ошибок в консоли.
// Собирает фронтенд с моками (VITE_MOCK=1) в dist-mock/, поднимает vite preview и проверяет Playwright.
// Запуск: npm run check:width
import { spawn, execSync } from 'node:child_process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
let chromium
try {
  ;({ chromium } = require('playwright'))
} catch {
  ;({ chromium } = require('@playwright/test'))
}

const PORT = 4179
const BASE = `http://127.0.0.1:${PORT}`
const WIDTH = 360

execSync('npx vite build --outDir dist-mock --emptyOutDir', {
  stdio: 'inherit',
  env: { ...process.env, VITE_MOCK: '1' },
})
const preview = spawn('npx', ['vite', 'preview', '--outDir', 'dist-mock', '--port', String(PORT), '--strictPort'], {
  stdio: 'ignore',
  detached: true,
})

async function waitForServer() {
  for (let i = 0; i < 50; i++) {
    try {
      if ((await fetch(BASE)).ok) return
    } catch {
      // ещё не поднялся
    }
    await new Promise((r) => setTimeout(r, 200))
  }
  throw new Error('vite preview не поднялся')
}

const results = []
let failed = false

async function measure(page, label) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  const ok = scrollWidth <= innerWidth
  failed ||= !ok
  results.push({ label, scrollWidth, innerWidth, ok })
}

try {
  await waitForServer()
  const browser = await chromium.launch()
  for (const colorScheme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width: WIDTH, height: 740 }, colorScheme })
    const page = await context.newPage()
    const errors = []
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
    page.on('pageerror', (e) => errors.push(String(e)))

    await page.goto(`${BASE}/`)
    await page.waitForURL('**/login**')
    await page.locator('#login-username').waitFor()
    await measure(page, `${colorScheme}: вход`)

    // ошибка входа тоже не должна раздвигать страницу
    await page.fill('#login-username', 'admin')
    await page.fill('#login-password', 'wrong-password')
    await page.click('button[type=submit]')
    await page.locator('[data-testid=login-error]').waitFor()
    await measure(page, `${colorScheme}: вход с ошибкой`)

    await page.fill('#login-password', 'admin12345')
    await page.click('button[type=submit]')
    await page.waitForURL('**/generate')
    await page.locator('header nav').waitFor()
    for (const path of ['generate', 'gallery', 'spending', 'profile', 'admin']) {
      await page.goto(`${BASE}/${path}`)
      await page.locator('main h1').waitFor()
      await measure(page, `${colorScheme}: layout /${path}`)
    }
    // 401 на неверный пароль — ожидаемая ошибка сети, остальное считаем дефектом
    const unexpected = errors.filter((e) => !e.includes('401'))
    if (unexpected.length) {
      failed = true
      results.push({ label: `${colorScheme}: ошибки консоли`, errors: unexpected, ok: false })
    }
    await context.close()
  }
  await browser.close()
} finally {
  process.kill(-preview.pid)
}

console.table(results)
if (failed) {
  console.error(`Есть горизонтальная прокрутка или ошибки на ширине ${WIDTH} px`)
  process.exit(1)
}
console.log(`OK: на ширине ${WIDTH} px scrollWidth <= innerWidth на всех экранах, ошибок в консоли нет`)
