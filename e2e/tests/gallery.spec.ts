// S-08: галереи и приватность с двумя пользователями.
import { expect, test } from '@playwright/test'
import { adminContext, createUser, userContext, waitDone } from '../helpers'

async function createWork(context: import('@playwright/test').BrowserContext, prompt: string, shared = true) {
  const response = await context.request.post('/api/generations', {
    multipart: {
      prompt,
      model: 'gpt-image-1-mini',
      quality: 'low',
      size: '1024x1024',
      shared: String(shared),
    },
  })
  expect(response.status()).toBe(202)
  const { ids } = await response.json()
  const done = await waitDone(context.request, ids[0])
  expect(done.status).toBe('done')
  return ids[0] as number
}

test('работа видна другому в «Общей», после выключения «Видна всем» пропадает, картинка — 404', async ({ browser }) => {
  const admin = await adminContext(browser)
  const alice = await createUser(admin.context, { prefix: 'alice' })
  const bob = await createUser(admin.context, { prefix: 'bob' })
  const aliceCtx = await userContext(browser, alice)
  const bobCtx = await userContext(browser, bob)

  const id = await createWork(aliceCtx, 'общая работа Алисы')

  const bobPage = await bobCtx.newPage()
  await bobPage.goto('/gallery')
  await bobPage.getByTestId('tab-shared').click()
  await expect(bobPage.getByTestId('work-card').first()).toBeVisible()
  await expect(bobPage.locator(`[data-work-id="${id}"]`)).toBeVisible()
  expect((await bobCtx.request.get(`/api/generations/${id}/image?kind=result`)).status()).toBe(200)

  const patch = await aliceCtx.request.patch(`/api/generations/${id}`, { data: { shared: false } })
  expect(patch.status()).toBe(200)

  await bobPage.reload()
  await bobPage.getByTestId('tab-shared').click()
  await expect(bobPage.locator(`[data-work-id="${id}"]`)).toHaveCount(0)
  expect((await bobCtx.request.get(`/api/generations/${id}/image?kind=result`)).status()).toBe(404)
  expect((await bobCtx.request.get(`/api/generations/${id}`)).status()).toBe(404)

  // администратор видит всё
  expect((await admin.context.request.get(`/api/generations/${id}`)).status()).toBe(200)
  expect((await admin.context.request.get(`/api/generations/${id}/image?kind=result`)).status()).toBe(200)
})
