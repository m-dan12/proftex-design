<!-- Профиль: имя, смена своего пароля (FR-02), выход из аккаунта. -->
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { auth } from '@/stores/auth'
import { formatMoney } from '../Spending/money'
import PasswordForm from './PasswordForm.vue'

const router = useRouter()
const user = computed(() => auth.state.user)

async function logout(): Promise<void> {
  await auth.logout()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <section class="page profile">
    <h1>Профиль</h1>

    <div v-if="user" class="card">
      <dl class="info">
        <dt>Логин</dt>
        <dd class="name" data-testid="profile-username">{{ user.username }}</dd>
        <dt>Роль</dt>
        <dd data-testid="profile-role">{{ user.is_admin ? 'Администратор' : 'Дизайнер' }}</dd>
        <dt>Дневной лимит</dt>
        <dd>{{ user.daily_limit_micro_usd === null ? 'без лимита' : formatMoney(user.daily_limit_micro_usd) }}</dd>
        <dt>В студии с</dt>
        <dd>{{ new Date(user.created_at).toLocaleDateString('ru-RU') }}</dd>
      </dl>
    </div>

    <PasswordForm />

    <div class="card">
      <h2>Выход</h2>
      <p class="muted">Сессия на этом устройстве закончится, войти можно будет снова по логину и паролю.</p>
      <button type="button" class="btn btn-danger" data-testid="profile-logout" @click="logout">
        Выйти из аккаунта
      </button>
    </div>
  </section>
</template>

<style scoped>
.profile {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  max-width: 560px;
}

.profile h1 {
  margin: 0;
}

.profile :deep(h2) {
  font-size: 17px;
  margin: 0 0 12px;
}

.info {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 6px 16px;
  margin: 0;
}

.info dt {
  color: var(--text-muted);
}

.info dd {
  margin: 0;
  min-width: 0;
}

.name {
  font-weight: 600;
  overflow-wrap: anywhere;
}

p {
  margin: 0 0 12px;
}
</style>
