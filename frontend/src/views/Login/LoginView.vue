<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import { auth } from '@/stores/auth'
import ThemeToggle from '@/components/ThemeToggle.vue'

const route = useRoute()
const router = useRouter()

const username = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

function safeRedirect(): string {
  const r = route.query.redirect
  // только внутренние пути, чтобы ?redirect= не уводил на чужой сайт
  return typeof r === 'string' && r.startsWith('/') && !r.startsWith('//') ? r : '/'
}

async function submit(): Promise<void> {
  if (busy.value) return
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = 'Введите логин и пароль'
    return
  }
  busy.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    await router.replace(safeRedirect())
  } catch (e) {
    password.value = ''
    if (e instanceof ApiError) {
      error.value = e.status === 401 ? 'Неверный логин или пароль' : e.detail
    } else {
      error.value = 'Сервер недоступен, попробуйте позже'
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="corner"><ThemeToggle /></div>
    <form class="card login" novalidate @submit.prevent="submit">
      <h1>Дизайн-студия</h1>
      <p class="muted">Войдите, чтобы генерировать изображения</p>
      <div class="field">
        <label for="login-username">Логин</label>
        <input
          id="login-username"
          v-model="username"
          class="input"
          name="username"
          autocomplete="username"
          autocapitalize="off"
          spellcheck="false"
          required
        />
      </div>
      <div class="field">
        <label for="login-password">Пароль</label>
        <input
          id="login-password"
          v-model="password"
          class="input"
          type="password"
          name="password"
          autocomplete="current-password"
          required
        />
      </div>
      <p v-if="error" class="error" role="alert" data-testid="login-error">{{ error }}</p>
      <button type="submit" class="btn btn-primary submit" :disabled="busy">
        {{ busy ? 'Входим…' : 'Войти' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--gap);
}

.corner {
  position: fixed;
  top: 8px;
  right: 8px;
}

.login {
  width: 100%;
  max-width: 360px;
  box-shadow: var(--shadow);
}

.login h1 {
  margin-bottom: 4px;
}

.login p.muted {
  margin: 0 0 20px;
}

.submit {
  width: 100%;
  margin-top: 4px;
}
</style>
