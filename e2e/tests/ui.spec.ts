// S-15: скорость и интерфейс — галерея из 50 работ, превью, ширина 360 px, консоль без ошибок.
import { expect, test } from '@playwright/test'
import { ADMIN_PASSWORD } from '../constants'
import { adminContext, createUser, newClient, apiLogin, userContext, waitDone } from '../helpers'

test('галерея из 50 работ ≤ 1,5 с, превью ≤ 60 КБ', async ({ browser }) => {
  test.setTimeout(240_000)
  const admin = await adminContext(browser)
  const user = await createUser(admin.context, { prefix: 'bulk' })
  const context = await userContext(browser, user)

  const ids: number[] = []
  for (let batch = 0; batch < 13; batch++) {
    const response = await context.request.post('/api/generations', {
      multipart: {
        prompt: `работа ${batch}`,
        model: 'gpt-image-1-mini',
        quality: 'low',
        size: '1024x1024',
        n: '4',
      },
    })
    expect(response.status()).toBe(202)
    ids.push(...(await response.json()).ids)
  }
  expect(ids.length).toBeGreaterThanOrEqual(50)
  for (const id of ids) expect((await waitDone(context.request, id, 120_000)).status).toBe('done')

  const page = await context.newPage()
  const started = Date.now()
  await page.goto('/gallery')
  await expect(page.getByTestId('work-card')).toHaveCount(50)
  await page.waitForFunction(() =>
    // Остальные картинки грузятся лениво, по мере прокрутки: проверяем те, что в экране.
    [...document.querySelectorAll<HTMLImageElement>('[data-testid="work-card"] img')]
      .filter((img) => img.getBoundingClientRect().top < window.innerHeight)
      .every((img) => img.complete && img.naturalWidth > 0),
  )
  expect(Date.now() - started).toBeLessThan(1500)

  for (const id of ids.slice(0, 5)) {
    const thumb = await context.request.get(`/api/generations/${id}/image?kind=thumb`)
    expect(thumb.status()).toBe(200)
    expect((await thumb.body()).length).toBeLessThanOrEqual(60 * 1024)
  }
})

test('360 px: нет горизонтальной прокрутки, в консоли нет ошибок', async ({ browser }) => {
  const { context } = await newClient(browser)
  await apiLogin(context, 'admin', ADMIN_PASSWORD)
  const page = await context.newPage()
  await page.setViewportSize({ width: 360, height: 740 })
  const problems: string[] = []
  page.on('console', (m) => m.type() === 'error' && problems.push(m.text()))
  page.on('pageerror', (e) => problems.push(String(e)))

  for (const path of ['/generate', '/gallery', '/spending', '/profile', '/admin']) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(scrollWidth, `горизонтальная прокрутка на ${path}`).toBeLessThanOrEqual(innerWidth)
  }
  expect(problems).toEqual([])
})
