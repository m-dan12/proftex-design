// Данные мок-API. Живут в памяти вкладки; resetMockDb() возвращает исходное состояние.
import type { Generation, ModelsResponse, User } from '@/api/client'

export interface MockUser extends User {
  password: string
}

export const MOCK_ACCOUNTS = {
  admin: { username: 'admin', password: 'admin12345' },
  designer: { username: 'designer', password: 'designer123' },
  blocked: { username: 'blocked', password: 'blocked123' },
} as const

export const MOCK_MODELS: ModelsResponse = {
  mode: 'mock',
  default_model: 'gpt-image-2.5-sunburst',
  models: [
    {
      id: 'gpt-image-2.5-sunburst',
      title: 'GPT Image 2.5 Sunburst',
      qualities: ['low', 'medium', 'high', 'auto'],
      default_quality: 'high',
      sizes: ['auto', '1024x1024', '1536x1024', '1024x1536'],
      output_formats: ['jpeg', 'png', 'webp'],
      supports_input_fidelity: true,
      max_n: 4,
      fallback_per_image_micro_usd: { low: 11000, medium: 42000, high: 167000, auto: 167000 },
    },
    {
      id: 'gpt-image-1-mini',
      title: 'GPT Image 1 Mini',
      qualities: ['low', 'medium', 'high'],
      default_quality: 'medium',
      sizes: ['1024x1024', '1536x1024', '1024x1536'],
      output_formats: ['jpeg', 'png'],
      supports_input_fidelity: false,
      max_n: 2,
      fallback_per_image_micro_usd: { low: 5000, medium: 11000, high: 36000 },
    },
  ],
}

export interface MockDb {
  users: MockUser[]
  generations: Generation[]
  nextUserId: number
  nextGenerationId: number
  sessionUserId: number | null
  failedLogins: number[]
}

const SESSION_KEY = 'mock-session'

function readSession(): number | null {
  try {
    const v = sessionStorage.getItem(SESSION_KEY)
    return v ? Number(v) : null
  } catch {
    return null
  }
}

export function saveSession(id: number | null): void {
  db.sessionUserId = id
  try {
    if (id === null) sessionStorage.removeItem(SESSION_KEY)
    else sessionStorage.setItem(SESSION_KEY, String(id))
  } catch {
    // без sessionStorage сессия живёт до перезагрузки
  }
}

function seedGenerations(): Generation[] {
  const base = Date.parse('2026-10-27T09:00:00Z')
  const prompts = [
    'Гостиная в скандинавском стиле, на диване подушки с принтом',
    'Ничего не менять, только уменьшить рюши на шторах',
    'Перенести принт ткани на кресло',
  ]
  return prompts.map((prompt, i) => ({
    id: i + 1,
    user_id: i === 2 ? 1 : 2,
    username: i === 2 ? 'admin' : 'designer',
    parent_id: i === 1 ? 1 : null,
    batch_id: `seed-${i + 1}`,
    variant_idx: 0,
    model: 'gpt-image-2.5-sunburst',
    quality: 'high',
    size: '1024x1024',
    input_fidelity: i === 1 ? 'high' : null,
    output_format: 'jpeg',
    prompt,
    status: 'done',
    error: null,
    shared: true,
    input_text_tokens: 40,
    input_image_tokens: i === 1 ? 1300 : 0,
    output_tokens: 4160,
    cost_micro_usd: 133_000 + i * 10_000,
    inputs: i === 1 ? [{ idx: 0, filename: null, source_generation_id: 1 }] : [],
    created_at: new Date(base + i * 3_600_000).toISOString(),
    finished_at: new Date(base + i * 3_600_000 + 20_000).toISOString(),
  }))
}

function initial(): MockDb {
  const created = '2026-10-01T00:00:00Z'
  return {
    users: [
      { id: 1, ...MOCK_ACCOUNTS.admin, is_admin: true, is_active: true, daily_limit_micro_usd: null, created_at: created },
      { id: 2, ...MOCK_ACCOUNTS.designer, is_admin: false, is_active: true, daily_limit_micro_usd: null, created_at: created },
      { id: 3, ...MOCK_ACCOUNTS.blocked, is_admin: false, is_active: false, daily_limit_micro_usd: null, created_at: created },
    ],
    generations: seedGenerations(),
    nextUserId: 4,
    nextGenerationId: 4,
    sessionUserId: readSession(),
    failedLogins: [],
  }
}

export const db: MockDb = initial()

export function resetMockDb(): void {
  Object.assign(db, initial())
  saveSession(null)
}

export function publicUser(u: MockUser): User {
  const { password: _password, ...user } = u
  return user
}
