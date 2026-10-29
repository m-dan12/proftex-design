// Типизированный клиент API. Типы генерируются из contracts/openapi.yaml
// командой `npm run gen:api` в src/api/types.ts — руками их не править.
import createClient, { type Middleware } from 'openapi-fetch'
import type { components, operations, paths } from './types'

export type Schemas = components['schemas']
export type User = Schemas['User']
export type ModelInfo = Schemas['ModelInfo']
export type ModelsResponse = Schemas['ModelsResponse']
export type Generation = Schemas['Generation']
export type GenerationStatus = Schemas['GenerationStatus']
export type GenerationList = Schemas['GenerationList']
export type GenerationCreated = Schemas['GenerationCreated']
export type MySpending = Schemas['MySpending']
export type AdminSpending = Schemas['AdminSpending']
export type SpendingBucket = Schemas['SpendingBucket']
export type Health = Schemas['Health']
export type OperationId = keyof operations

/** Ошибка API: HTTP-код и русский текст из `{"detail": "..."}`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

const FALLBACK_TEXT: Record<number, string> = {
  401: 'Нужно войти заново',
  403: 'Нет прав',
  404: 'Не найдено',
  413: 'Файл слишком большой',
  422: 'Неверные данные',
  429: 'Слишком много запросов, попробуйте позже',
}

function detailOf(status: number, body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string' && detail) return detail
    // FastAPI отдаёт ошибки валидации списком
    if (Array.isArray(detail)) return FALLBACK_TEXT[422]!
  }
  return FALLBACK_TEXT[status] ?? `Ошибка сервера (${status})`
}

/**
 * Достаёт данные из ответа openapi-fetch или бросает ApiError.
 *   const user = await unwrap(api.GET('/api/me'))
 */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise
  if (!response.ok) throw new ApiError(response.status, detailOf(response.status, error))
  return data as T
}

type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null

/** Вызывается при любом 401, кроме самого входа: сессия истекла или пользователя заблокировали. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler
}

const unauthorizedMiddleware: Middleware = {
  onResponse({ request, response }) {
    if (response.status === 401 && !new URL(request.url).pathname.endsWith('/api/auth/login')) {
      onUnauthorized?.()
    }
    return undefined
  },
}

function baseUrl(): string {
  return typeof location !== 'undefined' ? location.origin : 'http://localhost'
}

export const api = createClient<paths>({
  baseUrl: baseUrl(),
  credentials: 'same-origin',
  // fetch берётся в момент запроса, а не при импорте: так его перехватывает MSW в тестах
  fetch: (request) => globalThis.fetch(request),
})
api.use(unauthorizedMiddleware)

/** URL картинки работы для <img src> и ссылок «Скачать» (права проверяет бэкенд по cookie). */
export function imageUrl(
  id: number,
  kind: 'result' | 'thumb' | 'input',
  opts: { idx?: number; download?: boolean } = {},
): string {
  const q = new URLSearchParams({ kind })
  if (opts.idx !== undefined) q.set('idx', String(opts.idx))
  if (opts.download) q.set('download', 'true')
  return `/api/generations/${id}/image?${q}`
}

/** POST /api/generations: multipart с полями GenerationCreate (source_ids и files — повторяющиеся поля). */
export function createGeneration(form: FormData): Promise<GenerationCreated> {
  return unwrap(
    api.POST('/api/generations', {
      body: form as unknown as Schemas['GenerationCreate'],
      bodySerializer: (body) => body as unknown as FormData,
    }),
  )
}
