<script setup lang="ts">
// Плитка работы в сетке галереи: превью (лениво), автор, время, пометка приватности.
import { imageUrl, type Generation } from '@/api/client'
import { formatDateTime } from '@/utils/format'

defineProps<{ work: Generation; showAuthor: boolean }>()
defineEmits<{ open: [] }>()

const STATUS: Record<string, string> = { pending: 'В очереди…', running: 'Рисуется…', error: 'Ошибка' }
</script>

<template>
  <li class="tile" data-testid="work-card" :data-work-id="work.id">
    <button type="button" class="open" :aria-label="`Открыть работу #${work.id}`" @click="$emit('open')">
      <img
        v-if="work.status === 'done'"
        class="thumb"
        :src="imageUrl(work.id, 'thumb')"
        :alt="work.prompt.slice(0, 120)"
        loading="lazy"
        decoding="async"
        width="400"
        height="400"
      />
      <span v-else class="thumb status" :class="{ failed: work.status === 'error' }">{{ STATUS[work.status] }}</span>
    </button>
    <div class="caption">
      <span v-if="showAuthor" class="author">{{ work.username }}</span>
      <span class="time muted">{{ formatDateTime(work.created_at) }}</span>
      <span v-if="!work.shared" class="private" title="Видна только автору и администратору" data-testid="private-badge">
        приватная
      </span>
    </div>
  </li>
</template>

<style scoped>
.tile {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.open {
  display: block;
  width: 100%;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--surface-2);
  cursor: pointer;
}

.open:hover {
  border-color: var(--text-muted);
}

.thumb {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 1;
  object-fit: cover;
}

.status {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 14px;
}

.status.failed {
  color: var(--danger);
  background: var(--danger-soft);
}

.caption {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 8px;
  font-size: 12px;
  min-width: 0;
}

.author {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.private {
  padding: 0 6px;
  border-radius: 999px;
  color: var(--warning);
  border: 1px solid currentColor;
}
</style>
