<script setup lang="ts">
// Один запуск: варианты рядом, у каждого статус, а у готового — «Править дальше», «Повторить», «Скачать».
import { computed } from 'vue'
import { imageUrl, type Generation, type GenerationStatus } from '@/api/client'
import { formatMoney } from '@/utils/format'
import type { Batch } from './tracker'

const props = defineProps<{ batch: Batch }>()
const emit = defineEmits<{ edit: [g: Generation]; repeat: [g: Generation] }>()

const STATUS_TEXT: Record<GenerationStatus, string> = {
  pending: 'В очереди',
  running: 'Рисуется',
  done: 'Готово',
  error: 'Ошибка',
}

const variants = computed(() =>
  props.batch.ids.map((id) => ({ id, g: props.batch.items[id], gone: props.batch.gone.includes(id) })),
)
const first = computed(() => variants.value.find((v) => v.g)?.g)
const total = computed(() => variants.value.reduce((s, v) => s + (v.g?.cost_micro_usd ?? 0), 0))
const allDone = computed(() => variants.value.every((v) => v.g?.status === 'done'))
</script>

<template>
  <article class="card batch" data-testid="batch">
    <header class="batch-head">
      <p class="prompt" :title="props.batch.prompt">{{ props.batch.prompt }}</p>
      <p class="muted meta">
        <template v-if="first">{{ first.model }} · {{ first.quality }} · {{ first.size }}</template>
        <template v-if="allDone"> · {{ formatMoney(total) }}</template>
      </p>
    </header>
    <div class="variants" :class="`n${variants.length}`">
      <div v-for="v in variants" :key="v.id" class="variant" data-testid="variant" :data-status="v.g?.status ?? 'pending'">
        <div class="frame">
          <img
            v-if="v.g?.status === 'done'"
            :src="imageUrl(v.id, 'result')"
            :alt="v.g.prompt"
            data-testid="result-image"
          />
          <p v-else-if="v.gone" class="muted placeholder">Работа удалена</p>
          <p v-else-if="v.g?.status === 'error'" class="error placeholder" data-testid="variant-error">
            {{ v.g.error || 'Не удалось сгенерировать' }}
          </p>
          <div v-else class="placeholder"><span class="spinner" aria-hidden="true"></span></div>
        </div>
        <div class="variant-foot">
          <span class="status" :class="v.g?.status ?? 'pending'" data-testid="status">
            {{ v.gone ? '—' : STATUS_TEXT[v.g?.status ?? 'pending'] }}
          </span>
          <div v-if="v.g?.status === 'done'" class="buttons">
            <button type="button" class="btn" data-testid="edit-further" @click="emit('edit', v.g)">Править дальше</button>
            <button type="button" class="btn" data-testid="repeat" @click="emit('repeat', v.g)">Повторить</button>
            <a class="btn" :href="imageUrl(v.id, 'result', { download: true })" download data-testid="download">Скачать</a>
          </div>
          <div v-else-if="v.g?.status === 'error'" class="buttons">
            <button type="button" class="btn" data-testid="repeat" @click="emit('repeat', v.g)">Повторить</button>
          </div>
        </div>
      </div>
    </div>
  </article>
</template>

<style scoped>
.batch {
  min-width: 0;
}

.batch-head {
  margin-bottom: 8px;
}

.prompt {
  margin: 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow-wrap: anywhere;
}

.meta {
  margin: 2px 0 0;
  font-size: 13px;
}

.variants {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(130px, 100%), 1fr));
  gap: 12px 8px;
}

.variant {
  min-width: 0;
}

.frame {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 1;
  overflow: hidden;
  background: var(--surface-2);
  border-radius: 6px;
}

.frame img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.placeholder {
  margin: 8px;
  overflow-wrap: anywhere;
  font-size: 14px;
}

.spinner {
  display: inline-block;
  width: 28px;
  height: 28px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.variant-foot {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
}

.status {
  font-size: 13px;
  color: var(--text-muted);
}

.status.done {
  color: var(--success);
}

.status.running {
  color: var(--warning);
}

.status.error {
  color: var(--danger);
}

.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.buttons .btn {
  min-height: 32px;
  padding: 4px 10px;
  font-size: 14px;
}
</style>
