// Состояние входа. Без Pinia: одного reactive-объекта достаточно.
import { computed, reactive, readonly } from 'vue'
import { api, ApiError, unwrap, type User } from '@/api/client'

const state = reactive({
  user: null as User | null,
  loaded: false,
})

let loading: Promise<void> | null = null

/** Один раз узнаёт, есть ли сессия (GET /api/me). Повторные вызовы ждут тот же запрос. */
function ensureLoaded(): Promise<void> {
  if (state.loaded) return Promise.resolve()
  loading ??= unwrap(api.GET('/api/me'))
    .then((user) => {
      state.user = user
    })
    .catch(() => {
      state.user = null
    })
    .finally(() => {
      state.loaded = true
      loading = null
    })
  return loading
}

async function login(username: string, password: string): Promise<User> {
  const user = await unwrap(api.POST('/api/auth/login', { body: { username, password } }))
  state.user = user
  state.loaded = true
  return user
}

async function logout(): Promise<void> {
  try {
    await unwrap(api.POST('/api/auth/logout'))
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) throw e
  } finally {
    state.user = null
  }
}

/** Сессия пропала (401 на любом запросе): забыть пользователя. */
function forget(): void {
  state.user = null
  state.loaded = true
}

/** Сброс для тестов. */
function reset(): void {
  state.user = null
  state.loaded = false
  loading = null
}

export const auth = {
  state: readonly(state),
  isAdmin: computed(() => state.user?.is_admin === true),
  ensureLoaded,
  login,
  logout,
  forget,
  reset,
}
