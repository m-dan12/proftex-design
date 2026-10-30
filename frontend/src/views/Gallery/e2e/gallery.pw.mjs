// Playwright-проверки галереи (показатели 3, 6, 7 карточки T12) на мок-API.
// Поднимает vite в режиме моков (VITE_MOCK=1) на свободном порту и гоняет Chromium.
// Запуск из frontend/:  node src/views/Gallery/e2e/gallery.pw.mjs
// Файл .mjs, а не .spec.ts, чтобы его не подхватывал vitest.
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const require = createRequire(import.meta.url)
let chromium
try {
  ;({ chromium } = require('playwright'))
} catch {
  ;({ chromium } = require('@playwright/test'))
}

const ROOT = fileURLToPath(new URL('../../../..', import.meta.url))
process.env.VITE_MOCK = '1'

const results = []
let failed = false

function check(label, ok, detail = '') {
  results.push({ label, ok, detail })
  if (!ok) failed = true
}

async function noHorizontalScroll(page, label) {
  const { sw, iw } = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    iw: window.innerWidth,
  }))
  check(`${label}: нет горизонтальной прокрутки`, sw <= iw, `scrollWidth=${sw} innerWidth=${iw}`)
}

const dialogHasFocus = (page) =>
  page.evaluate(() => {
    const d = document.querySelector('[data-testid="work-dialog"]')
    return !!d && d.contains(document.activeElement)
  })

async function login(page, base) {
  await page.goto(`${base}/login`)
  await page.fill('#login-username', 'designer')
  await page.fill('#login-password', 'designer123')
  await page.click('button[type=submit]')
  await page.waitForURL('**/generate')
}

const server = await createServer({
  root: ROOT,
  configFile: `${ROOT}/vite.config.ts`,
  logLevel: 'error',
  // свободный порт ищет сам vite, начиная с 4190
  server: { port: 4190, strictPort: false, host: '127.0.0.1' },
})
await server.listen()
const base = server.resolvedUrls.local[0].replace(/\/$/, '')

const browser = await chromium.launch()
try {
  for (const colorScheme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 }, colorScheme })
    const page = await context.newPage()
    const errors = []
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
    page.on('pageerror', (e) => errors.push(String(e)))

    await login(page, base)
    // 401 на GET /api/me до входа ожидаем; считаем ошибки только после входа
    errors.length = 0
    await page.goto(`${base}/gallery`)
    await page.locator('[data-testid="work-card"]').first().waitFor()

    // 7. превью лениво грузятся; на 360 px нет горизонтальной прокрутки
    const lazy = await page.$$eval('[data-testid="work-card"] img', (imgs) => imgs.map((i) => i.loading))
    check(`${colorScheme}: превью с loading="lazy"`, lazy.length > 0 && lazy.every((l) => l === 'lazy'), lazy.join(','))
    await noHorizontalScroll(page, `${colorScheme}: «Мои»`)
    await page.click('[data-testid="tab-shared"]')
    await page.locator('[data-testid="author-filter"]').waitFor()
    await page.locator('[data-work-id="3"]').waitFor()
    await noHorizontalScroll(page, `${colorScheme}: «Общая»`)

    // 6. открываем с клавиатуры: фокус в диалоге, Tab/Shift+Tab не выходят, Esc возвращает фокус
    const opener = page.locator('[data-work-id="2"] button')
    await opener.focus()
    await page.keyboard.press('Enter')
    await page.locator('[data-testid="work-dialog"]').waitFor()
    await page.locator('[data-testid="work-dialog"] img').first().waitFor()
    await noHorizontalScroll(page, `${colorScheme}: диалог открыт`)
    check(`${colorScheme}: фокус в диалоге после открытия`, await dialogHasFocus(page))
    let escaped = 0
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press('Tab')
      if (!(await dialogHasFocus(page))) escaped++
    }
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press('Shift+Tab')
      if (!(await dialogHasFocus(page))) escaped++
    }
    check(`${colorScheme}: Tab и Shift+Tab не выводят фокус из диалога`, escaped === 0, `вышел ${escaped} раз из 50`)
    await page.keyboard.press('Escape')
    await page.locator('[data-testid="work-dialog"]').waitFor({ state: 'detached' })
    const back = await page.evaluate(
      () => document.activeElement?.closest('[data-work-id]')?.getAttribute('data-work-id') ?? null,
    )
    check(`${colorScheme}: Esc закрывает диалог и возвращает фокус на карточку`, back === '2', `фокус на ${back}`)
    check(`${colorScheme}: в адресе нет ?id после закрытия`, !page.url().includes('id='), page.url())

    // 3. удаление только после подтверждения, затем карточка исчезает
    await page.click('[data-testid="tab-mine"]')
    await page.locator('[data-work-id="2"]').waitFor()
    await page.click('[data-work-id="2"] button')
    await page.click('[data-testid="delete-work"]')
    await page.locator('[data-testid="confirm-delete"]').waitFor()
    check(
      `${colorScheme}: после «Удалить работу» работа ещё на месте`,
      (await page.locator('[data-work-id="2"]').count()) === 1,
    )
    await page.click('[data-testid="cancel-delete"]')
    check(
      `${colorScheme}: «Отмена» не удаляет`,
      (await page.locator('[data-work-id="2"]').count()) === 1 &&
        (await page.locator('[data-testid="delete-work"]').count()) === 1,
    )
    await page.click('[data-testid="delete-work"]')
    await page.click('[data-testid="confirm-delete"]')
    await page.locator('[data-testid="work-dialog"]').waitFor({ state: 'detached' })
    await page.locator('[data-work-id="2"]').waitFor({ state: 'detached' })
    check(`${colorScheme}: после подтверждения карточка исчезла`, (await page.locator('[data-work-id="2"]').count()) === 0)

    check(`${colorScheme}: нет ошибок в консоли`, errors.length === 0, errors.join(' | '))
    await context.close()
  }

  // Широкий экран: диалог рядом с сеткой, листание стрелками
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  await login(page, base)
  await page.goto(`${base}/gallery?tab=shared&id=3`)
  await page.locator('[data-testid="work-dialog"]').waitFor()
  await page.keyboard.press('ArrowRight')
  await page.waitForURL('**id=2**')
  check('1280: стрелка вправо листает на следующую работу', page.url().includes('id=2'), page.url())
  await page.click('[data-testid="edit-further"]')
  await page.waitForURL('**/generate?ref=2')
  check('1280: «Править дальше» ведёт на /generate?ref=2', page.url().endsWith('/generate?ref=2'), page.url())
  await context.close()
} finally {
  await browser.close()
  await server.close()
}

console.table(results)
if (failed) {
  console.error('Галерея: есть проваленные проверки')
  process.exit(1)
}
console.log(`OK: ${results.length} проверок галереи прошли`)
