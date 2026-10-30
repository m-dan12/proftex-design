<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { auth } from '@/stores/auth'
import ThemeToggle from './ThemeToggle.vue'

const router = useRouter()

const links = computed(() => [
  { to: { name: 'generate' }, label: 'Создать' },
  { to: { name: 'gallery' }, label: 'Галерея' },
  { to: { name: 'spending' }, label: 'Расходы' },
  { to: { name: 'profile' }, label: 'Профиль' },
  ...(auth.isAdmin.value ? [{ to: { name: 'admin' }, label: 'Админ' }] : []),
])

async function logout(): Promise<void> {
  await auth.logout()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <div class="layout">
    <header class="header">
      <div class="header-inner">
        <RouterLink :to="{ name: 'generate' }" class="brand">Дизайн-студия</RouterLink>
        <nav class="nav" aria-label="Разделы">
          <RouterLink
            v-for="link in links"
            :key="link.label"
            :to="link.to"
            class="nav-link"
            active-class="active"
            data-testid="nav-link"
          >
            {{ link.label }}
          </RouterLink>
        </nav>
        <div class="user">
          <span class="username" data-testid="username">{{ auth.state.user?.username }}</span>
          <ThemeToggle />
          <button type="button" class="btn btn-ghost" @click="logout">Выйти</button>
        </div>
      </div>
    </header>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 8px var(--gap);
  min-height: var(--header-h);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
}

.brand {
  font-weight: 600;
  color: var(--text);
  text-decoration: none;
  white-space: nowrap;
}

.nav {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1 1 auto;
  min-width: 0;
}

.nav-link {
  padding: 6px 10px;
  border-radius: 6px;
  color: var(--text-muted);
  text-decoration: none;
  white-space: nowrap;
}

.nav-link:hover {
  color: var(--text);
  background: var(--surface-2);
}

.nav-link.active {
  color: var(--accent);
  background: var(--accent-soft);
}

.user {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  min-width: 0;
}

.username {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 14px;
}

.main {
  flex: 1;
  min-width: 0;
}

/* Узкий экран: навигация отдельной строкой на всю ширину */
@media (max-width: 640px) {
  .nav {
    order: 3;
    flex-basis: 100%;
  }
}
</style>
