import zlib from 'node:zlib'
import { expect, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test'
import { ADMIN_PASSWORD } from './constants'

let ipCounter = 10

/** Уникальный «адрес клиента» для X-Forwarded-For: лимит попыток входа считается по IP. */
export function nextIp(): string {
  ipCounter += 1
  return `10.20.0.${ipCounter}`
}

export interface Account {
  username: string
  password: string
  ip: string
  id: number
}

/** Контекст со своим адресом клиента; заголовок идёт и из страницы, и из `context.request`. */
export async function newClient(browser: import('@playwright/test').Browser, ip = nextIp()) {
  const context = await browser.newContext({
    extraHTTPHeaders: { 'X-Forwarded-For': ip },
    viewport: { width: 1280, height: 900 },
  })
  return { context, ip }
}

export async function apiLogin(context: BrowserContext, username: string, password: string) {
  const response = await context.request.post('/api/auth/login', { data: { username, password } })
  expect(response.status(), await response.text()).toBe(200)
  return response
}

export async function adminContext(browser: import('@playwright/test').Browser) {
  const { context, ip } = await newClient(browser)
  await apiLogin(context, 'admin', ADMIN_PASSWORD)
  return { context, ip }
}

let userCounter = 0

/** Создаёт обычного пользователя (или администратора) от имени администратора. */
export async function createUser(
  admin: BrowserContext,
  opts: { prefix?: string; isAdmin?: boolean } = {},
): Promise<Account> {
  userCounter += 1
  const username = `${opts.prefix ?? 'user'}${Date.now() % 100000}x${userCounter}`
  const password = `pass-${username}`
  const response = await admin.request.post('/api/admin/users', {
    data: { username, password, is_admin: opts.isAdmin ?? false },
  })
  expect(response.status(), await response.text()).toBe(201)
  const body = await response.json()
  return { username, password, ip: nextIp(), id: body.id }
}

/** Входит в UI через форму. */
export async function uiLogin(page: Page, account: Pick<Account, 'username' | 'password'>) {
  await page.goto('/login')
  await page.getByLabel('Логин').fill(account.username)
  await page.getByLabel('Пароль').fill(account.password)
  await page.getByRole('button', { name: 'Войти' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
}

/** Контекст пользователя: вход по API, cookie общая для страниц и запросов. */
export async function userContext(browser: import('@playwright/test').Browser, account: Account) {
  const { context } = await newClient(browser, account.ip)
  await apiLogin(context, account.username, account.password)
  return context
}

/** Ждёт, пока работа выйдет из pending/running; возвращает её. */
export async function waitDone(request: APIRequestContext, id: number, timeoutMs = 30_000) {
  let last: { status: string } & Record<string, unknown> = { status: 'pending' }
  await expect
    .poll(
      async () => {
        const response = await request.get(`/api/generations/${id}`)
        last = await response.json()
        return last.status
      },
      { timeout: timeoutMs, intervals: [500] },
    )
    .toMatch(/done|error/)
  return last
}

/** Небольшой валидный PNG для загрузки референсом. */
export function pngBuffer(color: [number, number, number] = [200, 30, 30]): Buffer {
  // 1×1 PNG нужного цвета, собранный вручную (без зависимостей).
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    return c >>> 0
  })
  const crc = (buf: Buffer) => {
    let c = 0xffffffff
    for (const b of buf) c = crcTable[(c ^ b) & 0xff]! ^ (c >>> 8)
    return (c ^ 0xffffffff) >>> 0
  }
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4)
    len.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type), data])
    const sum = Buffer.alloc(4)
    sum.writeUInt32BE(crc(body))
    return Buffer.concat([len, body, sum])
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(1, 0)
  ihdr.writeUInt32BE(1, 4)
  ihdr[8] = 8
  ihdr[9] = 2
  const raw = Buffer.from([0, ...color])
  const { deflateSync } = zlib
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}
