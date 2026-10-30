<!-- Смена своего пароля: поля проверяются после выхода из поля и перед отправкой. -->
<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { api, ApiError, unwrap } from '@/api/client'

/** Минимальная длина нового пароля, как в контракте (PasswordChange.new_password). */
const MIN_LENGTH = 8

type Field = 'old' | 'new' | 'repeat'

const values = reactive<Record<Field, string>>({ old: '', new: '', repeat: '' })
const touched = reactive<Record<Field, boolean>>({ old: false, new: false, repeat: false })
const busy = ref(false)
const serverError = ref('')
const success = ref('')

function check(name: Field): string {
  switch (name) {
    case 'old':
      return values.old ? '' : 'Введите текущий пароль'
    case 'new':
      if (!values.new) return 'Введите новый пароль'
      return values.new.length < MIN_LENGTH ? `Новый пароль — не короче ${MIN_LENGTH} символов` : ''
    case 'repeat':
      if (!values.repeat) return 'Повторите новый пароль'
      return values.repeat !== values.new ? 'Пароли не совпадают' : ''
  }
}

/** Ошибки показываются только у полей, из которых уже вышли (или после попытки отправки). */
const errors = computed(() => ({
  old: touched.old ? check('old') : '',
  new: touched.new ? check('new') : '',
  repeat: touched.repeat ? check('repeat') : '',
}))

function blur(name: Field): void {
  // пустое поле при простом проходе Tab не ругаем — только при отправке
  if (values[name]) touched[name] = true
  // повтор зависит от нового пароля
  if (name === 'new' && values.repeat) touched.repeat = true
}

function input(): void {
  success.value = ''
  serverError.value = ''
}

function explain(e: unknown): string {
  if (!(e instanceof ApiError)) return 'Сервер недоступен, попробуйте позже'
  // 422 от валидации FastAPI приходит списком, клиент превращает его в общий текст
  if (e.status === 422 && e.detail === 'Неверные данные') {
    return `Не удалось сменить пароль: проверьте текущий пароль и длину нового (не короче ${MIN_LENGTH} символов)`
  }
  return e.detail
}

async function submit(): Promise<void> {
  if (busy.value) return
  touched.old = touched.new = touched.repeat = true
  serverError.value = ''
  success.value = ''
  if (check('old') || check('new') || check('repeat')) return
  busy.value = true
  try {
    await unwrap(api.POST('/api/me/password', { body: { old_password: values.old, new_password: values.new } }))
    values.old = values.new = values.repeat = ''
    touched.old = touched.new = touched.repeat = false
    success.value = 'Пароль изменён'
  } catch (e) {
    serverError.value = explain(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="card" novalidate data-testid="pw-form" @submit.prevent="submit">
    <h2>Смена пароля</h2>
    <div class="field">
      <label for="pw-old">Текущий пароль</label>
      <input
        id="pw-old"
        v-model="values.old"
        class="input"
        type="password"
        autocomplete="current-password"
        :aria-invalid="!!errors.old"
        :aria-describedby="errors.old ? 'pw-old-error' : undefined"
        data-testid="pw-old"
        @blur="blur('old')"
        @input="input"
      />
      <p v-if="errors.old" id="pw-old-error" class="field-error" data-testid="pw-old-error">{{ errors.old }}</p>
    </div>
    <div class="field">
      <label for="pw-new">Новый пароль</label>
      <input
        id="pw-new"
        v-model="values.new"
        class="input"
        type="password"
        autocomplete="new-password"
        :aria-invalid="!!errors.new"
        :aria-describedby="errors.new ? 'pw-new-error' : 'pw-new-hint'"
        data-testid="pw-new"
        @blur="blur('new')"
        @input="input"
      />
      <p v-if="errors.new" id="pw-new-error" class="field-error" data-testid="pw-new-error">{{ errors.new }}</p>
      <p v-else id="pw-new-hint" class="hint muted">Не короче {{ MIN_LENGTH }} символов</p>
    </div>
    <div class="field">
      <label for="pw-repeat">Повторите новый пароль</label>
      <input
        id="pw-repeat"
        v-model="values.repeat"
        class="input"
        type="password"
        autocomplete="new-password"
        :aria-invalid="!!errors.repeat"
        :aria-describedby="errors.repeat ? 'pw-repeat-error' : undefined"
        data-testid="pw-repeat"
        @blur="blur('repeat')"
        @input="input"
      />
      <p v-if="errors.repeat" id="pw-repeat-error" class="field-error" data-testid="pw-repeat-error">
        {{ errors.repeat }}
      </p>
    </div>
    <p v-if="serverError" class="error" role="alert" data-testid="pw-error">{{ serverError }}</p>
    <p v-if="success" class="success" role="status" data-testid="pw-success">{{ success }}</p>
    <button type="submit" class="btn btn-primary" :disabled="busy">
      {{ busy ? 'Сохраняем…' : 'Сменить пароль' }}
    </button>
  </form>
</template>

<style scoped>
.field-error,
.hint {
  margin: 0;
  font-size: 13px;
}

.field-error {
  color: var(--danger);
}

.error,
.success {
  margin: 0 0 12px;
}

.success {
  padding: 8px 12px;
  color: var(--success);
  background: var(--surface-2);
  border-radius: 6px;
}
</style>
