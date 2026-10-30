// Показатели 2, 3 и 6 карточки T11 в браузере (Playwright + Chromium) на мок-API.
// Поднимает `vite` в режиме моков (VITE_MOCK=1) и проверяет экран генерации:
//   2 — ввод → запуск → статусы pending, running, done → картинка на экране; ошибка показывает текст;
//   3 — «Править дальше» кладёт результат в референсы, в теле запроса приходят source_ids и parent_id;
//   6 — на ширине 360 px нет горизонтальной прокрутки (форма, результаты, выбор из галереи), нет ошибок в консоли.
// Запуск из frontend/: node src/views/Generate/e2e/generate.e2e.mjs
// Нужен dev-сервер, а не сборка: для статуса error скрипт помечает работу ошибкой прямо в данных мока
// (import('/src/mocks/db.ts') в странице) — мок T03 сам ошибок не выдаёт.
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
let chromium
try {
  ;({ chromium } = require('playwright'))
} catch {
  ;({ chromium } = require('@playwright/test'))
}

const FRONTEND = fileURLToPath(new URL('../../../../', import.meta.url))
const PORT = Number(process.env.T11_PORT ?? 4181)
const BASE = `http://127.0.0.1:${PORT}`
const ERROR_TEXT = 'Запрос отклонён модерацией OpenAI'

const server = spawn('npx', ['vite', '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], {
  cwd: FRONTEND,
  env: { ...process.env, VITE_MOCK: '1' },
  stdio: 'ignore',
  detached: true,
})

async function waitForServer() {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(BASE)).ok) return
    } catch {
      // ещё не поднялся
    }
    await new Promise((r) => setTimeout(r, 200))
  }
  throw new Error('vite не поднялся')
}

const results = []
function check(n, label, ok, detail = '') {
  results.push({ '№': n, проверка: label, итог: ok ? 'OK' : 'FAIL', detail })
}

/** Ждёт, пока вариант получит статус `status`. */
async function waitStatus(variant, status, timeout = 10_000) {
  await variant.and(variant.page().locator(`[data-status="${status}"]`)).waitFor({ timeout })
}

async function noHorizontalScroll(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
}

let browser
try {
  await waitForServer()
  browser = await chromium.launch()
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  // перехватываем тела POST /api/generations прямо в странице: MSW отвечает из service worker,
  // и page.on('request') multipart-тело не показывает
  await context.addInitScript(() => {
    window.__genPosts = []
    const orig = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      try {
        const req = input instanceof Request ? input : new Request(input, init)
        if (req.method === 'POST' && new URL(req.url).pathname === '/api/generations') {
          const fd = await req.clone().formData()
          window.__genPosts.push({
            prompt: fd.get('prompt'),
            n: fd.get('n'),
            source_ids: fd.getAll('source_ids'),
            parent_id: fd.get('parent_id'),
          })
        }
      } catch {
        // не мешаем запросу
      }
      return orig(input, init)
    }
  })
  const page = await context.newPage()
  const errors = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(String(e)))

  // вход
  await page.goto(`${BASE}/login`)
  await page.locator('#login-username').waitFor({ timeout: 30_000 })
  await page.fill('#login-username', 'designer')
  await page.fill('#login-password', 'designer123')
  await page.click('button[type=submit]')
  await page.waitForURL('**/generate')
  await page.locator('#gen-model option').first().waitFor({ state: 'attached' })

  // --- 2: ввод → запуск → pending → running → done → картинка ---
  await page.fill('#gen-prompt', 'Гостиная в скандинавском стиле')
  await page.selectOption('#gen-n', '2')
  const price = await page.locator('[data-testid=price]').innerText()
  await page.click('button[type=submit]')
  const batch = page.locator('[data-testid=batch]').first()
  const variant = batch.locator('[data-testid=variant]').first()
  const seen = []
  for (const s of ['pending', 'running', 'done']) {
    try {
      await waitStatus(variant, s)
      seen.push(s)
    } catch {
      seen.push(`нет ${s}`)
    }
  }
  const variantsCount = await batch.locator('[data-testid=variant]').count()
  await batch.locator('[data-testid=variant][data-status=done]').nth(1).waitFor({ timeout: 10_000 })
  const img = batch.locator('[data-testid=result-image]').first()
  await img.waitFor()
  await page.waitForFunction((el) => el.complete && el.naturalWidth > 0, await img.elementHandle())
  const natural = await img.evaluate((el) => el.naturalWidth)
  check(
    2,
    'статусы pending → running → done, картинка на экране, варианты рядом',
    seen.join(',') === 'pending,running,done' && natural > 0 && variantsCount === 2,
    `статусы: ${seen.join(' → ')}; naturalWidth=${natural}; вариантов=${variantsCount}; цена ${price}`,
  )

  // --- 2: ошибка показывает текст ---
  await page.fill('#gen-prompt', 'Запуск, который упадёт')
  await page.selectOption('#gen-n', '1')
  await page.click('button[type=submit]')
  await page.locator('[data-testid=batch]').nth(1).waitFor()
  await page.evaluate(async (text) => {
    const { db } = await import('/src/mocks/db.ts')
    for (const g of db.generations) {
      if (g.prompt === 'Запуск, который упадёт' && g.status !== 'done') {
        g.status = 'error'
        g.error = text
      }
    }
  }, ERROR_TEXT)
  const errBatch = page.locator('[data-testid=batch]').first()
  let errShown = ''
  try {
    await errBatch.locator('[data-testid=variant-error]').waitFor({ timeout: 10_000 })
    errShown = await errBatch.locator('[data-testid=variant-error]').innerText()
  } catch {
    errShown = '(нет)'
  }
  const errStatus = await errBatch.locator('[data-testid=status]').first().innerText()
  check(2, 'ошибка генерации показывает текст', errShown === ERROR_TEXT && errStatus === 'Ошибка', `«${errShown}», статус «${errStatus}»`)

  // --- 3: «Править дальше» → референс → source_ids и parent_id в теле запроса ---
  const doneBatch = page.locator('[data-testid=batch]').nth(1)
  const doneId = await doneBatch
    .locator('[data-testid=result-image]')
    .first()
    .evaluate((el) => Number(new URL(el.src).pathname.split('/')[3]))
  await doneBatch.locator('[data-testid=edit-further]').first().click()
  const refCount = await page.locator('[data-testid=ref-item]').count()
  await page.fill('#gen-prompt', 'Сделать стены светлее')
  await page.click('button[type=submit]')
  await page.waitForFunction(() => window.__genPosts.length >= 3)
  const posts = await page.evaluate(() => window.__genPosts)
  const last = posts[posts.length - 1]
  check(
    3,
    '«Править дальше» → референс, в запросе source_ids и parent_id',
    refCount === 1 && last.source_ids.length === 1 && last.source_ids[0] === String(doneId) && last.parent_id === String(doneId),
    `референсов ${refCount}; source_ids=${JSON.stringify(last.source_ids)}, parent_id=${last.parent_id}, работа №${doneId}`,
  )

  // --- 6: 360 px без горизонтальной прокрутки ---
  await page.setViewportSize({ width: 360, height: 740 })
  await page.locator('[data-testid=batch] [data-status=done]').first().waitFor()
  const w1 = await noHorizontalScroll(page)
  await page.click('text=Из галереи')
  await page.locator('[data-testid=picker-item]').first().waitFor()
  const w2 = await noHorizontalScroll(page)
  await page.click('[data-testid=gallery-picker] >> text=Закрыть')
  await page.emulateMedia({ colorScheme: 'dark' })
  const w3 = await noHorizontalScroll(page)
  const widthOk = [w1, w2, w3].every((w) => w.scrollWidth <= w.innerWidth)
  check(6, 'ширина 360 px: форма+результаты, выбор из галереи, тёмная тема', widthOk, [w1, w2, w3].map((w) => `${w.scrollWidth}/${w.innerWidth}`).join(', '))

  // 401 на GET /api/me до входа — ожидаемый ответ (как в check-width из T03), остальное считаем дефектом
  const unexpected = errors.filter((e) => !e.includes('401'))
  check(6, 'нет ошибок в консоли', unexpected.length === 0, unexpected.join(' | '))
} catch (e) {
  check('-', 'сценарий', false, String(e?.stack ?? e))
} finally {
  await browser?.close()
  try {
    process.kill(-server.pid)
  } catch {
    // уже остановлен
  }
}

console.table(results)
if (results.some((r) => r.итог !== 'OK')) {
  console.error('T11 e2e: есть ошибки')
  process.exit(1)
}
console.log('T11 e2e: OK')
