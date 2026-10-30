<!-- Админка (T14): вкладки «Пользователи» и «Расходы»; вкладка хранится в ?tab=users|spending. -->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import UsersTab from './UsersTab.vue'
import SpendingTab from './SpendingTab.vue'

type Tab = 'users' | 'spending'
const TABS: { id: Tab; label: string }[] = [
  { id: 'users', label: 'Пользователи' },
  { id: 'spending', label: 'Расходы' },
]

const route = useRoute()
const router = useRouter()

const tab = computed<Tab>(() => (route.query.tab === 'spending' ? 'spending' : 'users'))

function select(id: Tab): void {
  if (id !== tab.value) void router.replace({ query: { ...route.query, tab: id } })
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  const i = TABS.findIndex((t) => t.id === tab.value)
  const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length]!
  select(next.id)
  document.getElementById(`admin-tab-${next.id}`)?.focus()
}
</script>

<template>
  <section class="page admin">
    <h1>Админ</h1>
    <div class="tabs" role="tablist" aria-label="Разделы админки" data-testid="admin-tabs" @keydown="onKeydown">
      <button
        v-for="t in TABS"
        :id="`admin-tab-${t.id}`"
        :key="t.id"
        type="button"
        role="tab"
        :class="['tab', { active: tab === t.id }]"
        :aria-selected="tab === t.id"
        :aria-controls="`admin-panel-${t.id}`"
        :tabindex="tab === t.id ? 0 : -1"
        :data-testid="`tab-${t.id}`"
        @click="select(t.id)"
      >
        {{ t.label }}
      </button>
    </div>
    <div :id="`admin-panel-${tab}`" role="tabpanel" :aria-labelledby="`admin-tab-${tab}`" class="panel">
      <UsersTab v-if="tab === 'users'" />
      <SpendingTab v-else />
    </div>
  </section>
</template>

<style scoped>
.admin {
  min-width: 0;
}

.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: var(--gap);
  border-bottom: 1px solid var(--border);
}

.tab {
  padding: 8px 14px;
  margin-bottom: -1px;
  font: inherit;
  font-weight: 500;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
}

.tab.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}

.panel {
  min-width: 0;
}
</style>
