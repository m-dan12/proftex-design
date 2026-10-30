// S-11: админка — создание, сброс пароля, блокировка; плюс «Мои расходы» и сводка администратора.
import { expect, test } from '@playwright/test'
import { ADMIN_PASSWORD } from '../constants'
import { apiLogin, newClient, nextIp, uiLogin } from '../helpers'

test('создание, сброс пароля и блокировка через интерфейс', async ({ browser }) => {
  const { context } = await newClient(browser)
  const page = await context.newPage()
  await uiLogin(page, { username: 'admin', password: ADMIN_PASSWORD })
  await page.goto('/admin')

  const username = `designer${Date.now() % 100000}`
  await page.getByTestId('create-form').getByLabel('Логин').fill(username)
  await page.getByTestId('create-form').getByLabel('Пароль').fill('first-pass-1')
  await page.getByTestId('create-form').getByRole('button', { name: /Создать/ }).click()
  const row = page.getByTestId('user-row').filter({ hasText: username })
  await expect(row).toBeVisible()

  // повторный логин — понятная ошибка
  await page.getByTestId('create-form').getByLabel('Логин').fill(username)
  await page.getByTestId('create-form').getByLabel('Пароль').fill('first-pass-1')
  await page.getByTestId('create-form').getByRole('button', { name: /Создать/ }).click()
  await expect(page.getByTestId('create-error')).toBeVisible()

  // новый пользователь входит со своим паролем
  const user = await newClient(browser, nextIp())
  await apiLogin(user.context, username, 'first-pass-1')

  // сброс пароля: новый пароль виден один раз
  await row.getByTestId('reset-password').click()
  await page.getByTestId('dialog-confirm').click()
  const fresh = (await page.getByTestId('new-password').textContent())!.trim()
  expect(fresh).toHaveLength(12)
  await page.getByTestId('dialog-close').click()
  await expect(page.getByTestId('new-password')).toHaveCount(0)
  const relogin = await newClient(browser, nextIp())
  await apiLogin(relogin.context, username, fresh)
  const oldPass = await (await newClient(browser, nextIp())).context.request.post('/api/auth/login', {
    data: { username, password: 'first-pass-1' },
  })
  expect(oldPass.status()).toBe(401)

  // блокировка требует подтверждения; активная сессия перестаёт работать
  expect((await relogin.context.request.get('/api/me')).status()).toBe(200)
  await row.getByTestId('toggle-active').click()
  await page.getByTestId('dialog-confirm').click()
  await expect(row.getByTestId('blocked-badge')).toBeVisible()
  expect((await relogin.context.request.get('/api/me')).status()).toBe(401)
})

test('расходы: сумма строк равна итогу, CSV отдаётся', async ({ browser }) => {
  const { context } = await newClient(browser)
  await apiLogin(context, 'admin', ADMIN_PASSWORD)
  const today = new Date().toISOString().slice(0, 10)
  const from = '2026-01-01'
  const response = await context.request.get(`/api/admin/spending?from=${from}&to=${today}&group=user`)
  expect(response.status()).toBe(200)
  const data = await response.json()
  const sum = (data.rows as { cost_micro_usd: number }[]).reduce((s, r) => s + r.cost_micro_usd, 0)
  expect(sum).toBe(data.total_micro_usd)

  const csv = await context.request.get(`/api/admin/spending.csv?from=${from}&to=${today}&group=user`)
  expect(csv.status()).toBe(200)
  expect(csv.headers()['content-type']).toContain('text/csv')

  const page = await context.newPage()
  await page.goto('/spending')
  await expect(page.getByTestId('spend-total').or(page.getByTestId('spending-empty'))).toBeVisible()
})
