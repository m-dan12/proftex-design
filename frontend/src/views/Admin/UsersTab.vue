<!-- Вкладка «Пользователи»: таблица, создание, сброс пароля, блокировка и разблокировка. -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError, unwrap, type User } from '@/api/client'
import { auth } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import AdminDialog from './AdminDialog.vue'
import { validatePassword, validateUsername } from './validate'

const users = ref<User[]>([])
const loading = ref(true)
const listError = ref('')
const actionError = ref('')

const errorText = (e: unknown) => (e instanceof ApiError ? e.detail : 'Сервер недоступен, попробуйте позже')

async function load(): Promise<void> {
  loading.value = true
  listError.value = ''
  try {
    users.value = (await unwrap(api.GET('/api/admin/users'))).items
  } catch (e) {
    listError.value = errorText(e)
  } finally {
    loading.value = false
  }
}

function replaceUser(u: User): void {
  users.value = users.value.map((x) => (x.id === u.id ? u : x))
}

// --- создание ---
const newUsername = ref('')
const newPassword = ref('')
const newIsAdmin = ref(false)
const usernameError = ref('')
const passwordError = ref('')
const createError = ref('')
const creating = ref(false)
const created = ref('')

async function create(): Promise<void> {
  if (creating.value) return
  createError.value = ''
  created.value = ''
  const username = newUsername.value.trim()
  usernameError.value = validateUsername(username)
  passwordError.value = validatePassword(newPassword.value)
  if (usernameError.value || passwordError.value) return
  creating.value = true
  try {
    const user = await unwrap(
      api.POST('/api/admin/users', { body: { username, password: newPassword.value, is_admin: newIsAdmin.value } }),
    )
    users.value = [...users.value, user]
    created.value = `Пользователь ${user.username} создан`
    newUsername.value = ''
    newPassword.value = ''
    newIsAdmin.value = false
  } catch (e) {
    createError.value =
      e instanceof ApiError && e.status === 409 ? `Такой логин уже есть: ${username}` : errorText(e)
  } finally {
    creating.value = false
  }
}

// --- диалоги: подтверждение блокировки, подтверждение сброса, новый пароль ---
type Dialog =
  | { kind: 'block'; user: User }
  | { kind: 'reset'; user: User }
  | { kind: 'password'; user: User; password: string }

const dialog = ref<Dialog | null>(null)
const busy = ref(false)
const copied = ref(false)

function closeDialog(): void {
  // пароль живёт только в этом объекте: после закрытия его нигде нет
  dialog.value = null
  copied.value = false
}

async function setActive(user: User, isActive: boolean): Promise<void> {
  busy.value = true
  actionError.value = ''
  try {
    replaceUser(await unwrap(api.PATCH('/api/admin/users/{id}', { params: { path: { id: user.id } }, body: { is_active: isActive } })))
  } catch (e) {
    actionError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

function toggleActive(user: User): void {
  if (user.is_active) dialog.value = { kind: 'block', user }
  else void setActive(user, true)
}

async function confirmBlock(user: User): Promise<void> {
  await setActive(user, false)
  closeDialog()
}

async function confirmReset(user: User): Promise<void> {
  busy.value = true
  actionError.value = ''
  try {
    const { password } = await unwrap(
      api.POST('/api/admin/users/{id}/reset-password', { params: { path: { id: user.id } } }),
    )
    dialog.value = { kind: 'password', user, password }
  } catch (e) {
    closeDialog()
    actionError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

const passwordEl = ref<HTMLElement | null>(null)

async function copyPassword(password: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(password)
    copied.value = true
  } catch {
    // без доступа к буферу выделяем пароль, чтобы скопировать вручную
    const el = passwordEl.value
    const sel = window.getSelection()
    if (el && sel) {
      const range = document.createRange()
      range.selectNodeContents(el)
      sel.removeAllRanges()
      sel.addRange(range)
    }
  }
}

onMounted(load)
</script>

<template>
  <div class="users">
    <form class="card create" data-testid="create-form" novalidate @submit.prevent="create">
      <h2>Новый пользователь</h2>
      <div class="create-fields">
        <div class="field">
          <label for="new-username">Логин</label>
          <input
            id="new-username"
            v-model="newUsername"
            class="input"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            :aria-invalid="!!usernameError"
            aria-describedby="new-username-hint"
            @blur="usernameError = newUsername ? validateUsername(newUsername.trim()) : ''"
          />
          <small v-if="usernameError" class="field-error" data-testid="username-error">{{ usernameError }}</small>
          <small v-else id="new-username-hint" class="muted">Латиница, цифры, «.», «_», «-», от 3 символов</small>
        </div>
        <div class="field">
          <label for="new-password">Пароль</label>
          <input
            id="new-password"
            v-model="newPassword"
            class="input"
            type="password"
            autocomplete="new-password"
            :aria-invalid="!!passwordError"
            @blur="passwordError = newPassword ? validatePassword(newPassword) : ''"
          />
          <small v-if="passwordError" class="field-error" data-testid="password-error">{{ passwordError }}</small>
          <small v-else class="muted">Не короче 8 символов</small>
        </div>
      </div>
      <label class="check">
        <input v-model="newIsAdmin" type="checkbox" />
        Администратор
      </label>
      <p v-if="createError" class="error" role="alert" data-testid="create-error">{{ createError }}</p>
      <p v-if="created" class="ok" role="status">{{ created }}</p>
      <button type="submit" class="btn btn-primary" :disabled="creating">
        {{ creating ? 'Создаём…' : 'Создать' }}
      </button>
    </form>

    <p v-if="actionError" class="error" role="alert" data-testid="action-error">{{ actionError }}</p>
    <p v-if="listError" class="error" role="alert">
      {{ listError }}
      <button type="button" class="btn btn-ghost" @click="load">Повторить</button>
    </p>
    <p v-else-if="loading" class="muted">Загружаем пользователей…</p>

    <div v-if="!loading && !listError" class="table-wrap">
      <table class="table" data-testid="users-table">
        <thead>
          <tr>
            <th scope="col">Логин</th>
            <th scope="col">Создан</th>
            <th scope="col" class="actions-col">Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="u in users"
            :key="u.id"
            data-testid="user-row"
            :data-username="u.username"
            :class="{ blocked: !u.is_active }"
          >
            <td>
              <span class="name">{{ u.username }}</span>
              <span v-if="u.is_admin" class="badge">Админ</span>
              <span v-if="!u.is_active" class="badge badge-danger" data-testid="blocked-badge">Заблокирован</span>
            </td>
            <td class="nowrap muted">{{ formatDateTime(u.created_at) }}</td>
            <td class="actions-col">
              <div class="row-actions">
                <button type="button" class="btn" data-testid="reset-password" :disabled="busy" @click="dialog = { kind: 'reset', user: u }">
                  Сбросить пароль
                </button>
                <button
                  type="button"
                  :class="['btn', u.is_active ? 'btn-danger' : '']"
                  data-testid="toggle-active"
                  :disabled="busy || u.id === auth.state.user?.id"
                  :title="u.id === auth.state.user?.id ? 'Нельзя заблокировать себя' : undefined"
                  @click="toggleActive(u)"
                >
                  {{ u.is_active ? 'Заблокировать' : 'Разблокировать' }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <AdminDialog v-if="dialog?.kind === 'block'" title="Заблокировать пользователя?" @close="closeDialog">
      <p>
        <b>{{ dialog.user.username }}</b> не сможет войти, его текущие сессии перестанут работать.
        Работы и расходы сохранятся.
      </p>
      <template #actions>
        <button type="button" class="btn" data-testid="dialog-cancel" @click="closeDialog">Отмена</button>
        <button type="button" class="btn btn-danger" data-testid="dialog-confirm" :disabled="busy" @click="confirmBlock(dialog.user)">
          Заблокировать
        </button>
      </template>
    </AdminDialog>

    <AdminDialog v-else-if="dialog?.kind === 'reset'" title="Сбросить пароль?" @close="closeDialog">
      <p>
        Старый пароль <b>{{ dialog.user.username }}</b> перестанет работать. Новый пароль покажем один раз —
        передайте его пользователю.
      </p>
      <template #actions>
        <button type="button" class="btn" data-testid="dialog-cancel" @click="closeDialog">Отмена</button>
        <button type="button" class="btn btn-primary" data-testid="dialog-confirm" :disabled="busy" @click="confirmReset(dialog.user)">
          Сбросить
        </button>
      </template>
    </AdminDialog>

    <AdminDialog v-else-if="dialog?.kind === 'password'" title="Новый пароль" @close="closeDialog">
      <p>Пароль для <b>{{ dialog.user.username }}</b>. После закрытия окна его больше нельзя будет посмотреть.</p>
      <code ref="passwordEl" class="password" data-testid="new-password">{{ dialog.password }}</code>
      <template #actions>
        <button type="button" class="btn" data-testid="copy-password" @click="copyPassword(dialog.password)">
          {{ copied ? 'Скопировано' : 'Скопировать' }}
        </button>
        <button type="button" class="btn btn-primary" data-testid="dialog-close" @click="closeDialog">Готово</button>
      </template>
    </AdminDialog>
  </div>
</template>

<style scoped>
.users {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
}

.create h2 {
  font-size: 17px;
}

.create-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
  gap: 0 var(--gap);
}

.field-error {
  color: var(--danger);
}

.check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.ok {
  color: var(--success);
}

.create .error,
.create .ok {
  margin: 0 0 12px;
}

.table-wrap {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  padding: 8px 12px;
  text-align: left;
  vertical-align: middle;
  border-bottom: 1px solid var(--border);
}

.table th {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  background: var(--surface-2);
}

.table tbody tr:last-child td {
  border-bottom: none;
}

.nowrap {
  white-space: nowrap;
}

.name {
  font-weight: 500;
  margin-right: 6px;
}

tr.blocked .name {
  color: var(--text-muted);
  text-decoration: line-through;
}

.badge {
  display: inline-block;
  padding: 0 6px;
  margin-right: 4px;
  font-size: 12px;
  border-radius: 4px;
  color: var(--accent);
  background: var(--accent-soft);
  white-space: nowrap;
}

.badge-danger {
  color: var(--danger);
  background: var(--danger-soft);
}

.actions-col {
  text-align: right;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  white-space: nowrap;
}

.password {
  display: block;
  padding: 10px 12px;
  font-size: 18px;
  letter-spacing: 0.05em;
  text-align: center;
  user-select: all;
  word-break: break-all;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
}
</style>
