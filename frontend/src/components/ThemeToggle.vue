<script setup lang="ts">
import { computed } from 'vue'
import { cycleTheme, theme } from '@/theme'

const LABELS = { system: 'Тема: как в системе', light: 'Тема: светлая', dark: 'Тема: тёмная' }

const label = computed(() => LABELS[theme.value])
</script>

<template>
  <button type="button" class="btn btn-ghost theme" :title="label" :aria-label="label" @click="cycleTheme">
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2">
      <template v-if="theme === 'light'">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </template>
      <path v-else-if="theme === 'dark'" d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
      <template v-else>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" />
      </template>
    </svg>
  </button>
</template>

<style scoped>
.theme {
  min-width: 36px;
  padding: 6px 8px;
}
</style>
