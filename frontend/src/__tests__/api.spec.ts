import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError, createGeneration, imageUrl, setUnauthorizedHandler, unwrap } from '@/api/client'
import { handlersByOperation } from '@/mocks/handlers'
import { MOCK_ACCOUNTS } from '@/mocks/db'
import { auth } from '@/stores/auth'

const contract = readFileSync(resolve(__dirname, '../../../contracts/openapi.yaml'), 'utf8')
const operationIds = [...contract.matchAll(/operationId:\s*(\w+)/g)].map((m) => m[1])

const loginAs = (who: keyof typeof MOCK_ACCOUNTS) =>
  auth.login(MOCK_ACCOUNTS[who].username, MOCK_ACCOUNTS[who].password)

describe('мок-API', () => {
  it('покрывает все 19 операций контракта', () => {
    expect(operationIds).toHaveLength(19)
    expect(Object.keys(handlersByOperation).sort()).toEqual([...operationIds].sort())
  })

  it('без входа /api/me → 401 с detail', async () => {
    await expect(unwrap(api.GET('/api/me'))).rejects.toMatchObject({ status: 401, detail: 'Нужно войти' })
  })

  it('health доступен без входа', async () => {
    expect(await unwrap(api.GET('/api/health'))).toEqual({ status: 'ok', mode: 'mock', disk_free_pct: 63.2 })
  })

  it('обычный пользователь на /api/admin/* получает 403', async () => {
    await loginAs('designer')
    const e = await unwrap(api.GET('/api/admin/users')).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).status).toBe(403)
  })

  it('генерация проходит pending → done, попадает в галерею и в расходы', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    try {
      await loginAs('designer')
      const models = await unwrap(api.GET('/api/models'))
      const form = new FormData()
      form.set('prompt', 'Тестовый промпт')
      form.set('model', models.default_model)
      form.set('quality', 'high')
      form.set('size', '1024x1024')
      form.set('n', '3')
      form.append('source_ids', '1')
      form.set('parent_id', '1')
      const created = await createGeneration(form)
      expect(created.ids).toHaveLength(3)

      const pending = await unwrap(api.GET('/api/generations/{id}', { params: { path: { id: created.ids[0]! } } }))
      expect(pending.status).toBe('pending')
      expect(pending.parent_id).toBe(1)

      vi.setSystemTime(Date.now() + 5000)
      const list = await unwrap(api.GET('/api/generations', { params: { query: { scope: 'mine' } } }))
      const batch = list.items.filter((g) => g.batch_id === created.batch_id)
      expect(batch.map((g) => g.status)).toEqual(['done', 'done', 'done'])

      const today = new Date().toISOString().slice(0, 10)
      const spending = await unwrap(api.GET('/api/spending/me', { params: { query: { from: today, to: today } } }))
      expect(spending.count).toBe(3)
      expect(spending.total_micro_usd).toBe(batch.reduce((s, g) => s + g.cost_micro_usd, 0))
    } finally {
      vi.useRealTimers()
    }
  })

  it('неизвестная модель → 422', async () => {
    await loginAs('designer')
    const form = new FormData()
    form.set('prompt', 'x')
    form.set('model', 'nope')
    form.set('quality', 'high')
    form.set('size', '1024x1024')
    const e = await createGeneration(form).catch((x: unknown) => x)
    expect((e as ApiError).status).toBe(422)
  })

  it('админ: создание, сброс пароля, блокировка, CSV', async () => {
    await loginAs('admin')
    const user = await unwrap(api.POST('/api/admin/users', { body: { username: 'new.one', password: 'password1' } }))
    const { password } = await unwrap(
      api.POST('/api/admin/users/{id}/reset-password', { params: { path: { id: user.id } } }),
    )
    expect(password).toHaveLength(12)
    const blocked = await unwrap(
      api.PATCH('/api/admin/users/{id}', { params: { path: { id: user.id } }, body: { is_active: false } }),
    )
    expect(blocked.is_active).toBe(false)
    const csv = await api.GET('/api/admin/spending.csv', {
      params: { query: { from: '2026-10-01', to: '2026-10-31', group: 'user' } },
      parseAs: 'arrayBuffer',
    })
    const bytes = new Uint8Array(csv.data!)
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]) // BOM для Excel
    expect(new TextDecoder().decode(bytes)).toMatch(/^key;label;count;cost_usd\r\n/)
  })
})

describe('клиент', () => {
  it('401 на обычном запросе вызывает обработчик выхода, на входе — нет', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    await api.POST('/api/auth/login', { body: { username: 'x', password: 'y' } })
    expect(handler).not.toHaveBeenCalled()
    await api.GET('/api/me')
    expect(handler).toHaveBeenCalledOnce()
  })

  it('imageUrl собирает адрес картинки', () => {
    expect(imageUrl(5, 'input', { idx: 2, download: true })).toBe(
      '/api/generations/5/image?kind=input&idx=2&download=true',
    )
  })
})
