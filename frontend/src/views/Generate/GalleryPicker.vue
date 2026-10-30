<script setup lang="ts">
// Выбор прошлых работ из галереи как референсов (вкладки «Мои» и «Общая», только готовые работы).
import { onMounted, ref } from 'vue'
import { ApiError, api, imageUrl, unwrap, type Generation } from '@/api/client'

const props = defineProps<{ selected: number[]; left: number }>()
const emit = defineEmits<{ pick: [g: Generation]; close: [] }>()

const scope = ref<'mine' | 'shared'>('mine')
const items = ref<Generation[]>([])
const cursor = ref<string | null>(null)
const loading = ref(false)
const error = ref('')

async function load(more = false): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const query: { scope: 'mine' | 'shared'; limit: number; cursor?: string } = { scope: scope.value, limit: 30 }
    if (more && cursor.value) query.cursor = cursor.value
    const page = await unwrap(api.GET('/api/generations', { params: { query } }))
    const done = page.items.filter((g) => g.status === 'done')
    items.value = more ? [...items.value, ...done] : done
    cursor.value = page.next_cursor
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Сервер недоступен, попробуйте позже'
  } finally {
    loading.value = false
  }
}

function switchTab(s: 'mine' | 'shared'): void {
  if (scope.value === s) return
  scope.value = s
  items.value = []
  cursor.value = null
  void load()
}

onMounted(() => void load())
</script>

<template>
  <div class="overlay" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="card picker" role="dialog" aria-modal="true" aria-label="Работы из галереи" data-testid="gallery-picker">
      <div class="picker-head">
        <h2>Из галереи</h2>
        <button type="button" class="btn btn-ghost" @click="emit('close')">Закрыть</button>
      </div>
      <div class="tabs">
        <button type="button" class="btn" :class="{ 'btn-primary': scope === 'mine' }" @click="switchTab('mine')">
          Мои
        </button>
        <button type="button" class="btn" :class="{ 'btn-primary': scope === 'shared' }" @click="switchTab('shared')">
          Общая
        </button>
        <span class="muted">Можно добавить ещё {{ props.left }}</span>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="!loading && !items.length" class="muted">Готовых работ пока нет</p>
      <div class="grid">
        <button
          v-for="g in items"
          :key="g.id"
          type="button"
          class="tile"
          :class="{ chosen: props.selected.includes(g.id) }"
          :disabled="props.selected.includes(g.id) || props.left <= 0"
          :title="g.prompt"
          data-testid="picker-item"
          @click="emit('pick', g)"
        >
          <img :src="imageUrl(g.id, 'thumb')" :alt="g.prompt" loading="lazy" />
        </button>
      </div>
      <button v-if="cursor" type="button" class="btn more" :disabled="loading" @click="load(true)">Ещё</button>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--gap);
  background: rgb(0 0 0 / 45%);
}

.picker {
  width: 100%;
  max-width: 760px;
  max-height: 100%;
  overflow: auto;
  box-shadow: var(--shadow);
}

.picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.picker-head h2 {
  margin: 0;
  font-size: 18px;
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 12px 0;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 8px;
}

.tile {
  padding: 0;
  aspect-ratio: 1;
  overflow: hidden;
  background: var(--surface-2);
  border: 2px solid transparent;
  border-radius: 6px;
  cursor: pointer;
}

.tile:disabled {
  cursor: default;
  opacity: 0.5;
}

.tile.chosen {
  border-color: var(--accent);
}

.tile img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.more {
  margin-top: 12px;
}
</style>
