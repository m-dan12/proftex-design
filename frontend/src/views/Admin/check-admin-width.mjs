// Показатель 6 карточки T14: на ширине 360 px у админки нет горизонтальной прокрутки страницы,
// таблицы прокручиваются внутри своего контейнера (overflow-x: auto), ошибок в консоли нет.
// Собирает фронтенд с моками (VITE_MOCK=1) во временную папку, поднимает vite preview и проверяет Playwright.
// Запуск из frontend/: node src/views/Admin/check-admin-width.mjs
import { spawn, execSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
let chromium
try {
  ;({ chromium } = require('playwright'))
} catch {
  ;({ chromium } = require('@playwright/test'))
}

const PORT = 4183
const BASE = `http://127.0.0.1:${PORT}`
const WIDTH = 360
const outDir = mkdtempSync(join(tmpdir(), 'admin-width-'))

execSync(`npx vite build --outDir ${outDir} --emptyOutDir`, {
  stdio: 'inherit',
  env: { ...process.env, VITE_MOCK: '1' },
})
const preview = spawn('npx', ['vite', 'preview', '--outDir', outDir, '--port', String(PORT), '--strictPort'], {
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
  const m = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    tables: Array.from(document.querySelectorAll('.table-wrap')).map((el) => ({
      overflowX: getComputedStyle(el).overflowX,
      right: Math.round(el.getBoundingClientRect().right),
      scrollsInside: el.scrollWidth > el.clientWidth,
    })),
  }))
  const tablesOk = m.tables.every((t) => t.overflowX === 'auto' && t.right <= m.innerWidth)
  const ok = m.scrollWidth <= m.innerWidth && tablesOk
  failed ||= !ok
  results.push({ label, scrollWidth: m.scrollWidth, innerWidth: m.innerWidth, tables: m.tables.length, scrollsInside: m.tables.some((t) => t.scrollsInside), tablesOk, ok })
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

    await page.goto(`${BASE}/login`)
    await page.fill('#login-username', 'admin')
    await page.fill('#login-password', 'admin12345')
    await page.click('button[type=submit]')
    await page.waitForURL('**/generate')

    await page.goto(`${BASE}/admin`)
    await page.locator('[data-testid=users-table]').waitFor()
    // длинный логин, чтобы таблица была шире экрана
    await page.fill('#new-username', 'very.long.user_name-for-width')
    await page.fill('#new-password', 'password123')
    await page.click('[data-testid=create-form] button[type=submit]')
    await page.locator('[data-username="very.long.user_name-for-width"]').waitFor()
    await measure(page, `${colorScheme}: пользователи`)

    await page.fill('#new-username', 'ab')
    await page.fill('#new-password', 'x')
    await page.click('[data-testid=create-form] button[type=submit]')
    await page.locator('[data-testid=username-error]').waitFor()
    await measure(page, `${colorScheme}: ошибки формы`)

    await page.locator('[data-username=designer] [data-testid=reset-password]').click()
    await page.click('[data-testid=dialog-confirm]')
    await page.locator('[data-testid=new-password]').waitFor()
    await measure(page, `${colorScheme}: диалог нового пароля`)
    await page.keyboard.press('Escape')
    await page.locator('[data-testid=new-password]').waitFor({ state: 'detached' })

    await page.click('[data-testid=tab-spending]')
    await page.click('[data-testid=period-custom]')
    await page.fill('#spend-from', '2026-10-01')
    await page.fill('#spend-to', '2026-10-31')
    for (const group of ['user', 'model', 'day']) {
      await page.selectOption('#spend-group', group)
      await page.locator('[data-testid=spend-row]').first().waitFor()
      await measure(page, `${colorScheme}: расходы, группировка ${group}`)
    }

    // 401 на GET /api/me до входа — ожидаемая ошибка сети, остальное считаем дефектом
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
  rmSync(outDir, { recursive: true, force: true })
}

console.table(results)
if (failed) {
  console.error(`Админка: есть горизонтальная прокрутка страницы или ошибки на ширине ${WIDTH} px`)
  process.exit(1)
}
console.log(`OK: админка на ширине ${WIDTH} px без горизонтальной прокрутки, таблицы прокручиваются внутри`)
