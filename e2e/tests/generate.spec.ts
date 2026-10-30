// S-04 (без референсов), S-05 (с референсами), S-06 (правка цепочкой), S-10 (модели).
import { expect, test } from '@playwright/test'
import { adminContext, createUser, pngBuffer, userContext, waitDone } from '../helpers'

test('генерация n=3 без референсов: done, один batch_id, формат и размер как выбраны', async ({ browser }) => {
  const admin = await adminContext(browser)
  const user = await createUser(admin.context)
  const context = await userContext(browser, user)
  const page = await context.newPage()
  await page.goto('/generate')

  await page.getByLabel('Промпт').or(page.locator('textarea')).first().fill('красная чашка на белом столе')
  await page.getByLabel('Размер').selectOption('1024x1024')
  await page.getByLabel('Формат').selectOption('png')
  await page.getByLabel('Вариантов').selectOption('3')

  const started = Date.now()
  await page.getByRole('button', { name: 'Сгенерировать' }).click()
  const variants = page.getByTestId('variant')
  await expect(variants).toHaveCount(3)
  await expect(page.locator('[data-testid="variant"][data-status="done"]')).toHaveCount(3, {
    timeout: 30_000,
  })
  expect(Date.now() - started).toBeLessThan(15_000 + 5_000) // ≤ 15 с на работу, с запасом на очередь

  const list = await (await context.request.get('/api/generations?scope=mine')).json()
  const batch = list.items.filter((g: { prompt: string }) => g.prompt === 'красная чашка на белом столе')
  expect(batch).toHaveLength(3)
  expect(new Set(batch.map((g: { batch_id: string }) => g.batch_id)).size).toBe(1)

  const image = await context.request.get(`/api/generations/${batch[0].id}/image?kind=result`)
  expect(image.status()).toBe(200)
  expect(image.headers()['content-type']).toBe('image/png')
  const bytes = await image.body()
  expect(bytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
  expect(bytes.readUInt32BE(16)).toBe(1024) // ширина из IHDR
  expect(bytes.readUInt32BE(20)).toBe(1024) // высота
})

test('генерация с тремя референсами и правка цепочкой (S-05, S-06)', async ({ browser }) => {
  const admin = await adminContext(browser)
  const user = await createUser(admin.context)
  const context = await userContext(browser, user)
  const page = await context.newPage()
  await page.goto('/generate')

  await page.getByTestId('file-input').setInputFiles(
    [[200, 30, 30], [30, 200, 30], [30, 30, 200]].map((c, i) => ({
      name: `ref${i}.png`,
      mimeType: 'image/png',
      buffer: pngBuffer(c as [number, number, number]),
    })),
  )
  await expect(page.getByTestId('ref-item')).toHaveCount(3)
  await page.locator('textarea').first().fill('собери из трёх референсов логотип')
  await page.getByRole('button', { name: 'Сгенерировать' }).click()
  await expect(page.locator('[data-testid="variant"][data-status="done"]')).toHaveCount(1, {
    timeout: 30_000,
  })

  const first = (await (await context.request.get('/api/generations?scope=mine')).json()).items[0]
  expect(first.inputs).toHaveLength(3)

  // Правка цепочкой: «Править дальше» из результата A — B с parent_id = A, A среди референсов B.
  await page.getByTestId('edit-further').click()
  await expect(page.getByTestId('parent-note')).toContainText(`№${first.id}`)
  await page.locator('textarea').first().fill('сделай фон темнее')
  await page.getByRole('button', { name: 'Сгенерировать' }).click()
  await expect(page.locator('[data-testid="variant"][data-status="done"]')).toHaveCount(2, {
    timeout: 30_000,
  })

  const items = (await (await context.request.get('/api/generations?scope=mine')).json()).items
  const second = items.find((g: { prompt: string }) => g.prompt === 'сделай фон темнее')
  expect(second.parent_id).toBe(first.id)
  const detail = await waitDone(context.request, second.id)
  expect(detail.status).toBe('done')
  expect((detail.inputs as { source_generation_id: number | null }[]).some((i) => i.source_generation_id === first.id)).toBe(true)
})

test('модели из models.json видны в форме; неизвестная модель и качество дают 422', async ({ browser }) => {
  const admin = await adminContext(browser)
  const user = await createUser(admin.context)
  const context = await userContext(browser, user)
  const models = (await (await context.request.get('/api/models')).json()) as {
    models: { id: string; title: string }[]
  }
  const page = await context.newPage()
  await page.goto('/generate')
  await expect(page.locator('#gen-model option')).toHaveText(models.models.map((m) => m.title))

  const bad = await context.request.post('/api/generations', {
    multipart: { prompt: 'x', model: 'нет-такой', quality: 'high', size: '1024x1024' },
  })
  expect(bad.status()).toBe(422)
  const badQuality = await context.request.post('/api/generations', {
    multipart: { prompt: 'x', model: models.models[0]!.id, quality: 'ultra', size: '1024x1024' },
  })
  expect(badQuality.status()).toBe(422)
})
