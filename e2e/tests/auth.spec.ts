// S-03: вход и роли.
import { expect, test } from '@playwright/test'
import { ADMIN_PASSWORD } from '../constants'
import { adminContext, apiLogin, createUser, newClient, nextIp, uiLogin } from '../helpers'

test('верный пароль: 200 и cookie HttpOnly + SameSite=Lax', async ({ browser }) => {
  const admin = await adminContext(browser)
  const user = await createUser(admin.context)
  const { context } = await newClient(browser, user.ip)
  const response = await context.request.post('/api/auth/login', {
    data: { username: user.username, password: user.password },
  })
  expect(response.status()).toBe(200)
  const cookie = response.headers()['set-cookie'] ?? ''
  expect(cookie).toMatch(/HttpOnly/i)
  expect(cookie).toMatch(/SameSite=Lax/i)
  // Secure выставляется при COOKIE_SECURE=1 (на VDS); в e2e по http он выключен, проверка — в pytest.
})

test('неверный пароль: 401, 6-я попытка с одного IP: 429, другой IP входит', async ({ browser }) => {
  const admin = await adminContext(browser)
  const user = await createUser(admin.context)
  const noisy = await newClient(browser, nextIp())
  for (let i = 0; i < 5; i++) {
    const response = await noisy.context.request.post('/api/auth/login', {
      data: { username: user.username, password: 'wrong-password' },
    })
    expect(response.status()).toBe(401)
  }
  const sixth = await noisy.context.request.post('/api/auth/login', {
    data: { username: user.username, password: 'wrong-password' },
  })
  expect(sixth.status()).toBe(429)

  const other = await createUser(admin.context)
  const quiet = await newClient(browser, nextIp())
  await apiLogin(quiet.context, other.username, other.password)
})

test('заблокированный: 403 при входе, активная сессия перестаёт работать', async ({ browser }) => {
  const admin = await adminContext(browser)
  const user = await createUser(admin.context)
  const { context } = await newClient(browser, user.ip)
  await apiLogin(context, user.username, user.password)
  expect((await context.request.get('/api/me')).status()).toBe(200)

  const blocked = await admin.context.request.patch(`/api/admin/users/${user.id}`, {
    data: { is_active: false },
  })
  expect(blocked.status()).toBe(200)

  expect((await context.request.get('/api/me')).status()).toBe(401)
  const again = await context.request.post('/api/auth/login', {
    data: { username: user.username, password: user.password },
  })
  expect(again.status()).toBe(403)
})

test('обычный пользователь не открывает /api/admin/*', async ({ browser }) => {
  const admin = await adminContext(browser)
  const user = await createUser(admin.context)
  const { context } = await newClient(browser, user.ip)
  await apiLogin(context, user.username, user.password)
  expect((await context.request.get('/api/admin/users')).status()).toBe(403)
  expect((await context.request.get('/api/admin/spending?from=2026-01-01&to=2026-12-31&group=user')).status()).toBe(403)
  const anonymous = await newClient(browser)
  expect((await anonymous.context.request.get('/api/admin/users')).status()).toBe(401)
})

test('вход через форму, выход и редирект с /admin для обычного пользователя', async ({ browser }) => {
  const admin = await adminContext(browser)
  const user = await createUser(admin.context)
  const { context } = await newClient(browser, user.ip)
  const page = await context.newPage()

  await page.goto('/gallery')
  await expect(page).toHaveURL(/\/login/)
  await uiLogin(page, user)
  await expect(page.getByTestId('profile-logout').or(page.getByRole('navigation'))).toBeVisible()

  await page.goto('/admin')
  await expect(page).not.toHaveURL(/\/admin/)

  await page.goto('/profile')
  await expect(page.getByTestId('profile-username')).toHaveText(user.username)
  await page.getByTestId('profile-logout').click()
  await expect(page).toHaveURL(/\/login/)
})

test('администратор из ADMIN_PASSWORD создан при старте', async ({ browser }) => {
  const { context } = await newClient(browser)
  const response = await apiLogin(context, 'admin', ADMIN_PASSWORD)
  expect((await response.json()).is_admin).toBe(true)
})
