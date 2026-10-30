<script setup lang="ts">
// Зона референсов: перетаскивание, выбор файла, вставка из буфера (её ловит экран), миниатюры с удалением.
import { ref } from 'vue'
import { MAX_REFS, type RefItem } from './references'

const props = defineProps<{ items: RefItem[] }>()
const emit = defineEmits<{ files: [files: File[]]; remove: [key: string]; pick: [] }>()

const input = ref<HTMLInputElement | null>(null)
const over = ref(false)

function onDrop(e: DragEvent): void {
  over.value = false
  const files = [...(e.dataTransfer?.files ?? [])]
  if (files.length) emit('files', files)
}

function onChoose(e: Event): void {
  const el = e.target as HTMLInputElement
  const files = [...(el.files ?? [])]
  el.value = ''
  if (files.length) emit('files', files)
}
</script>

<template>
  <div class="refs">
    <div
      class="drop"
      :class="{ over }"
      data-testid="drop-zone"
      @dragover.prevent="over = true"
      @dragleave="over = false"
      @drop.prevent="onDrop"
    >
      <p class="muted">Перетащите картинки сюда или вставьте из буфера (Ctrl+V)</p>
      <div class="actions">
        <button type="button" class="btn" :disabled="props.items.length >= MAX_REFS" @click="input?.click()">
          Выбрать файлы
        </button>
        <button type="button" class="btn" :disabled="props.items.length >= MAX_REFS" @click="emit('pick')">
          Из галереи
        </button>
        <span class="muted count" data-testid="refs-count">{{ props.items.length }} / {{ MAX_REFS }}</span>
      </div>
      <input
        ref="input"
        class="hidden"
        type="file"
        multiple
        accept="image/png,image/jpeg,image/webp"
        data-testid="file-input"
        @change="onChoose"
      />
    </div>
    <ul v-if="props.items.length" class="thumbs" data-testid="refs">
      <li v-for="item in props.items" :key="item.key" class="thumb" data-testid="ref-item">
        <img v-if="item.url" :src="item.url" :alt="item.kind === 'file' ? item.file.name : `Работа №${item.generationId}`" />
        <span class="label">{{ item.kind === 'file' ? item.file.name : `№${item.generationId}` }}</span>
        <button type="button" class="remove" aria-label="Убрать референс" title="Убрать" @click="emit('remove', item.key)">
          ×
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.drop {
  padding: 12px;
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  text-align: center;
}

.drop.over {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.drop p {
  margin: 0 0 8px;
  font-size: 14px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.hidden {
  display: none;
}

.thumbs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: 8px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.thumb {
  position: relative;
  aspect-ratio: 1;
  overflow: hidden;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.label {
  position: absolute;
  inset: auto 0 0;
  padding: 1px 4px;
  overflow: hidden;
  font-size: 11px;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--text);
  background: color-mix(in srgb, var(--surface) 80%, transparent);
}

.remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 24px;
  height: 24px;
  padding: 0;
  font-size: 16px;
  line-height: 1;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 50%;
  cursor: pointer;
}
</style>
