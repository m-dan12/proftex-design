// MSW-обработчики для всех 19 операций contracts/openapi.yaml.
// Поведение упрощённое, но коды ответов и формы тел — как в контракте.
import { http, HttpResponse, type HttpHandler, type JsonBodyType } from 'msw'
import type { Generation, OperationId, Schemas, SpendingBucket } from '@/api/client'
import { db, MOCK_MODELS, publicUser, saveSession, type MockUser } from './db'

const API = '*/api'

/** Через сколько мс задача переходит в running и в done. */
export const MOCK_TIMING = { running: 1000, done: 3000 }
const startedAt = new Map<number, number>()

const err = (status: number, detail: string) => HttpResponse.json({ detail }, { status })
const json = <T extends JsonBodyType>(body: T, status = 200) => HttpResponse.json(body, { status })

function currentUser(): MockUser | null {
  const u = db.users.find((x) => x.id === db.sessionUserId)
  return u && u.is_active ? u : null
}

type Guard = { user: MockUser; fail?: never } | { user?: never; fail: Response }

function requireUser(): Guard {
  const user = currentUser()
  if (!user) {
    saveSession(null)
    return { fail: err(401, 'Нужно войти') }
  }
  return { user }
}

function requireAdmin(): Guard {
  const g = requireUser()
  if (g.fail) return g
  if (!g.user.is_admin) return { fail: err(403, 'Только для администратора') }
  return g
}

function advance(g: Generation): Generation {
  if (g.status === 'done' || g.status === 'error') return g
  const elapsed = Date.now() - (startedAt.get(g.id) ?? 0)
  if (elapsed >= MOCK_TIMING.done) {
    const model = MOCK_MODELS.models.find((m) => m.id === g.model)
    g.status = 'done'
    g.input_text_tokens = 40
    g.input_image_tokens = g.inputs.length * 1300
    g.output_tokens = 4160
    g.cost_micro_usd = model?.fallback_per_image_micro_usd[g.quality] ?? 0
    g.finished_at = new Date().toISOString()
  } else if (elapsed >= MOCK_TIMING.running) {
    g.status = 'running'
  }
  return g
}

function canRead(user: MockUser, g: Generation): boolean {
  return user.is_admin || g.user_id === user.id || g.shared
}

function canEdit(user: MockUser, g: Generation): boolean {
  return user.is_admin || g.user_id === user.id
}

function findGeneration(id: string | readonly string[] | undefined): Generation | undefined {
  return db.generations.find((g) => g.id === Number(id))
}

function svgImage(g: Generation, label: string): string {
  const hue = (g.id * 67) % 360
  const [w, h] = /^\d+x\d+$/.test(g.size) ? g.size.split('x').map(Number) : [1024, 1024]
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<rect width="100%" height="100%" fill="hsl(${hue} 55% 62%)"/>
<text x="50%" y="50%" font-family="sans-serif" font-size="${Math.round(Number(w) / 12)}" fill="#fff" text-anchor="middle" dominant-baseline="middle">#${g.id} ${label}</text>
</svg>`
}

function inPeriod(g: Generation, from: string, to: string): boolean {
  const day = g.created_at.slice(0, 10)
  return g.status === 'done' && day >= from && day <= to
}

function period(url: URL): { from: string; to: string } | null {
  const from = url.searchParams.get('from')
  const to = url.searchParams.get('to')
  const re = /^\d{4}-\d{2}-\d{2}$/
  if (!from || !to || !re.test(from) || !re.test(to) || from > to) return null
  return { from, to }
}

function group(items: Generation[], key: (g: Generation) => [string, string]): SpendingBucket[] {
  const map = new Map<string, SpendingBucket>()
  for (const g of items) {
    const [k, label] = key(g)
    const b = map.get(k) ?? { key: k, label, count: 0, cost_micro_usd: 0 }
    b.count += 1
    b.cost_micro_usd += g.cost_micro_usd
    map.set(k, b)
  }
  return [...map.values()].sort((a, b) => a.key.localeCompare(b.key))
}

const byDay = (g: Generation): [string, string] => [g.created_at.slice(0, 10), g.created_at.slice(0, 10)]
const byModel = (g: Generation): [string, string] => [g.model, MOCK_MODELS.models.find((m) => m.id === g.model)?.title ?? g.model]
const byUser = (g: Generation): [string, string] => [String(g.user_id), g.username]

function adminSpending(url: URL): Schemas['AdminSpending'] | Response {
  const p = period(url)
  const grp = url.searchParams.get('group')
  if (!p || (grp !== 'user' && grp !== 'model' && grp !== 'day')) return err(422, 'Неверный период или группировка')
  for (const g of db.generations) advance(g)
  const items = db.generations.filter((g) => inPeriod(g, p.from, p.to))
  const rows = group(items, grp === 'user' ? byUser : grp === 'model' ? byModel : byDay)
  return {
    ...p,
    group: grp,
    total_micro_usd: items.reduce((s, g) => s + g.cost_micro_usd, 0),
    count: items.length,
    rows,
  }
}

function generatePassword(): string {
  const abc = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  return Array.from({ length: 12 }, () => abc[Math.floor(Math.random() * abc.length)]).join('')
}

/** operationId → обработчик. Тест проверяет, что здесь все операции контракта. */
export const handlersByOperation: Record<OperationId, HttpHandler> = {
  login: http.post(`${API}/auth/login`, async ({ request }) => {
    const body = (await request.json().catch(() => null)) as Partial<Schemas['LoginRequest']> | null
    if (!body?.username || !body.password) return err(422, 'Введите логин и пароль')
    const now = Date.now()
    db.failedLogins = db.failedLogins.filter((t) => now - t < 60_000)
    if (db.failedLogins.length >= 5) return err(429, 'Слишком много попыток входа, подождите минуту')
    const user = db.users.find((u) => u.username === body.username)
    if (!user || user.password !== body.password) {
      db.failedLogins.push(now)
      return err(401, 'Неверный логин или пароль')
    }
    if (!user.is_active) return err(403, 'Пользователь заблокирован')
    saveSession(user.id)
    return json(publicUser(user))
  }),

  logout: http.post(`${API}/auth/logout`, () => {
    const g = requireUser()
    if (g.fail) return g.fail
    saveSession(null)
    return new HttpResponse(null, { status: 204 })
  }),

  getMe: http.get(`${API}/me`, () => {
    const g = requireUser()
    return g.fail ?? json(publicUser(g.user))
  }),

  changeMyPassword: http.post(`${API}/me/password`, async ({ request }) => {
    const g = requireUser()
    if (g.fail) return g.fail
    const body = (await request.json().catch(() => null)) as Partial<Schemas['PasswordChange']> | null
    if (!body?.old_password || !body.new_password) return err(422, 'Заполните оба поля')
    if (body.old_password !== g.user.password) return err(422, 'Старый пароль неверный')
    if (body.new_password.length < 8) return err(422, 'Новый пароль — не короче 8 символов')
    g.user.password = body.new_password
    return new HttpResponse(null, { status: 204 })
  }),

  listModels: http.get(`${API}/models`, () => {
    const g = requireUser()
    return g.fail ?? json(MOCK_MODELS)
  }),

  createGeneration: http.post(`${API}/generations`, async ({ request }) => {
    const g = requireUser()
    if (g.fail) return g.fail
    const form = await request.formData().catch(() => null)
    if (!form) return err(422, 'Ожидается multipart/form-data')
    const prompt = String(form.get('prompt') ?? '').trim()
    const model = MOCK_MODELS.models.find((m) => m.id === form.get('model'))
    const quality = String(form.get('quality') ?? '')
    const size = String(form.get('size') ?? '')
    const n = Number(form.get('n') ?? 1)
    const outputFormat = String(form.get('output_format') ?? 'jpeg') as Generation['output_format']
    if (!prompt || prompt.length > 4000) return err(422, 'Промпт: от 1 до 4000 символов')
    if (!model) return err(422, 'Неизвестная модель')
    if (!model.qualities.includes(quality)) return err(422, 'Недопустимое качество')
    if (!model.sizes.includes(size)) return err(422, 'Недопустимый размер')
    if (!model.output_formats.includes(outputFormat)) return err(422, 'Недопустимый формат')
    if (!Number.isInteger(n) || n < 1 || n > model.max_n) return err(422, `Вариантов: от 1 до ${model.max_n}`)

    const sourceIds = form.getAll('source_ids').map(Number)
    for (const id of sourceIds) {
      const src = findGeneration(String(id))
      if (!src || !canRead(g.user, src)) return err(404, `Работа ${id} не найдена`)
    }
    const files = form.getAll('files').filter((f): f is File => typeof f !== 'string')
    if (sourceIds.length + files.length > 10) return err(422, 'Не больше 10 референсов')
    if (files.some((f) => f.size > 20 * 1024 * 1024)) return err(413, 'Файл больше 20 МБ')
    const parentRaw = form.get('parent_id')
    const parentId = parentRaw ? Number(parentRaw) : null
    if (parentId !== null && !sourceIds.includes(parentId)) return err(422, 'parent_id должен быть среди source_ids')

    const inputs: Generation['inputs'] = [
      ...sourceIds.map((id, idx) => ({ idx, filename: null, source_generation_id: id })),
      ...files.map((f, i) => ({ idx: sourceIds.length + i, filename: f.name, source_generation_id: null })),
    ]
    const fidelity = form.get('input_fidelity')
    const batchId = `mock-${Date.now().toString(36)}`
    const ids: number[] = []
    for (let v = 0; v < n; v++) {
      const id = db.nextGenerationId++
      ids.push(id)
      startedAt.set(id, Date.now())
      db.generations.push({
        id,
        user_id: g.user.id,
        username: g.user.username,
        parent_id: parentId,
        batch_id: batchId,
        variant_idx: v,
        model: model.id,
        quality,
        size,
        input_fidelity:
          model.supports_input_fidelity && inputs.length ? (fidelity === 'low' ? 'low' : 'high') : null,
        output_format: outputFormat,
        prompt,
        status: 'pending',
        error: null,
        shared: form.get('shared') !== 'false',
        input_text_tokens: 0,
        input_image_tokens: 0,
        output_tokens: 0,
        cost_micro_usd: 0,
        inputs,
        created_at: new Date().toISOString(),
        finished_at: null,
      })
    }
    return json({ batch_id: batchId, ids }, 202)
  }),

  listGenerations: http.get(`${API}/generations`, ({ request }) => {
    const g = requireUser()
    if (g.fail) return g.fail
    const url = new URL(request.url)
    const scope = url.searchParams.get('scope')
    if (scope !== 'mine' && scope !== 'shared') return err(422, 'scope: mine или shared')
    const limit = Math.min(Number(url.searchParams.get('limit') ?? 50) || 50, 50)
    const cursor = Number(url.searchParams.get('cursor') ?? 0)
    const author = url.searchParams.get('author_id')
    const items = db.generations
      .map(advance)
      .filter((x) => (scope === 'mine' ? x.user_id === g.user.id : x.shared || g.user.is_admin))
      .filter((x) => !author || x.user_id === Number(author))
      .filter((x) => !cursor || x.id < cursor)
      .sort((a, b) => b.id - a.id)
    const page = items.slice(0, limit)
    const next = items.length > limit ? String(page[page.length - 1]!.id) : null
    return json({ items: page, next_cursor: next })
  }),

  getGeneration: http.get(`${API}/generations/:id`, ({ params }) => {
    const g = requireUser()
    if (g.fail) return g.fail
    const item = findGeneration(params.id)
    if (!item || !canRead(g.user, item)) return err(404, 'Работа не найдена')
    return json(advance(item))
  }),

  updateGeneration: http.patch(`${API}/generations/:id`, async ({ params, request }) => {
    const g = requireUser()
    if (g.fail) return g.fail
    const item = findGeneration(params.id)
    if (!item || !canRead(g.user, item)) return err(404, 'Работа не найдена')
    if (!canEdit(g.user, item)) return err(403, 'Менять может только автор')
    const body = (await request.json().catch(() => null)) as Partial<Schemas['GenerationPatch']> | null
    if (typeof body?.shared !== 'boolean') return err(422, 'Поле shared обязательно')
    item.shared = body.shared
    return json(advance(item))
  }),

  deleteGeneration: http.delete(`${API}/generations/:id`, ({ params }) => {
    const g = requireUser()
    if (g.fail) return g.fail
    const item = findGeneration(params.id)
    if (!item || !canRead(g.user, item)) return err(404, 'Работа не найдена')
    if (!canEdit(g.user, item)) return err(403, 'Удалить может только автор')
    advance(item)
    if (item.status === 'pending' || item.status === 'running') return err(409, 'Работа ещё выполняется')
    db.generations = db.generations.filter((x) => x !== item)
    return new HttpResponse(null, { status: 204 })
  }),

  getGenerationImage: http.get(`${API}/generations/:id/image`, ({ params, request }) => {
    const g = requireUser()
    if (g.fail) return g.fail
    const item = findGeneration(params.id)
    if (!item || !canRead(g.user, item)) return err(404, 'Работа не найдена')
    const url = new URL(request.url)
    const kind = url.searchParams.get('kind')
    const idx = Number(url.searchParams.get('idx') ?? -1)
    let label: string
    if (kind === 'result' || kind === 'thumb') {
      if (advance(item).status !== 'done') return err(404, 'Картинка ещё не готова')
      label = kind === 'thumb' ? 'превью' : 'результат'
    } else if (kind === 'input') {
      if (!item.inputs.some((i) => i.idx === idx)) return err(404, 'Референс не найден')
      label = `референс ${idx + 1}`
    } else {
      return err(422, 'kind: result, thumb или input')
    }
    const headers: Record<string, string> = { 'Content-Type': 'image/svg+xml' }
    if (url.searchParams.get('download') === 'true') {
      headers['Content-Disposition'] = `attachment; filename="design-${item.id}.svg"`
    }
    return new HttpResponse(svgImage(item, label), { headers })
  }),

  getMySpending: http.get(`${API}/spending/me`, ({ request }) => {
    const g = requireUser()
    if (g.fail) return g.fail
    const p = period(new URL(request.url))
    if (!p) return err(422, 'Неверный период')
    for (const x of db.generations) advance(x)
    const items = db.generations.filter((x) => x.user_id === g.user.id && inPeriod(x, p.from, p.to))
    return json({
      ...p,
      total_micro_usd: items.reduce((s, x) => s + x.cost_micro_usd, 0),
      count: items.length,
      by_day: group(items, byDay),
      by_model: group(items, byModel),
    })
  }),

  getAdminSpending: http.get(`${API}/admin/spending`, ({ request }) => {
    const g = requireAdmin()
    if (g.fail) return g.fail
    const res = adminSpending(new URL(request.url))
    return res instanceof Response ? res : json(res)
  }),

  getAdminSpendingCsv: http.get(`${API}/admin/spending.csv`, ({ request }) => {
    const g = requireAdmin()
    if (g.fail) return g.fail
    const res = adminSpending(new URL(request.url))
    if (res instanceof Response) return res
    const usd = (m: number) => (m / 1_000_000).toFixed(6)
    const lines = [
      'key;label;count;cost_usd',
      ...res.rows.map((r) => `${r.key};${r.label};${r.count};${usd(r.cost_micro_usd)}`),
      `total;Итого;${res.count};${usd(res.total_micro_usd)}`,
    ]
    return new HttpResponse('\ufeff' + lines.join('\r\n') + '\r\n', {
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="spending-${res.from}-${res.to}.csv"`,
      },
    })
  }),

  listUsers: http.get(`${API}/admin/users`, () => {
    const g = requireAdmin()
    return g.fail ?? json({ items: db.users.map(publicUser) })
  }),

  createUser: http.post(`${API}/admin/users`, async ({ request }) => {
    const g = requireAdmin()
    if (g.fail) return g.fail
    const body = (await request.json().catch(() => null)) as Partial<Schemas['UserCreate']> | null
    if (!body?.username || !/^[A-Za-z0-9._-]{3,32}$/.test(body.username)) {
      return err(422, 'Логин: 3–32 символа, латиница, цифры, «.», «_», «-»')
    }
    if (!body.password || body.password.length < 8) return err(422, 'Пароль — не короче 8 символов')
    if (db.users.some((u) => u.username === body.username)) return err(409, 'Такой логин уже есть')
    const user: MockUser = {
      id: db.nextUserId++,
      username: body.username,
      password: body.password,
      is_admin: body.is_admin ?? false,
      is_active: true,
      daily_limit_micro_usd: null,
      created_at: new Date().toISOString(),
    }
    db.users.push(user)
    return json(publicUser(user), 201)
  }),

  updateUser: http.patch(`${API}/admin/users/:id`, async ({ params, request }) => {
    const g = requireAdmin()
    if (g.fail) return g.fail
    const user = db.users.find((u) => u.id === Number(params.id))
    if (!user) return err(404, 'Пользователь не найден')
    const body = (await request.json().catch(() => null)) as Schemas['UserPatch'] | null
    if (!body || Object.keys(body).length === 0) return err(422, 'Нечего менять')
    const losesAdmin = user.is_admin && user.is_active && (body.is_active === false || body.is_admin === false)
    const activeAdmins = db.users.filter((u) => u.is_admin && u.is_active).length
    if (losesAdmin && activeAdmins <= 1) return err(409, 'Нельзя отключить последнего администратора')
    if (body.is_active !== undefined) user.is_active = body.is_active
    if (body.is_admin !== undefined) user.is_admin = body.is_admin
    if (body.daily_limit_micro_usd !== undefined) user.daily_limit_micro_usd = body.daily_limit_micro_usd
    return json(publicUser(user))
  }),

  resetUserPassword: http.post(`${API}/admin/users/:id/reset-password`, ({ params }) => {
    const g = requireAdmin()
    if (g.fail) return g.fail
    const user = db.users.find((u) => u.id === Number(params.id))
    if (!user) return err(404, 'Пользователь не найден')
    user.password = generatePassword()
    return json({ password: user.password })
  }),

  getHealth: http.get(`${API}/health`, () => json({ status: 'ok', mode: 'mock', disk_free_pct: 63.2 })),
}

export const handlers = Object.values(handlersByOperation)
