<script setup lang="ts">
// Диалог работы: результат, референсы, параметры и действия.
// Esc закрывает, стрелки влево/вправо листают, фокус не выходит из диалога.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError, imageUrl, unwrap, type Generation } from '@/api/client'
import { formatDateTime, formatUsd } from '@/utils/format'
import { useFocusTrap } from './useFocusTrap'

const props = defineProps<{
  work: Generation
  canEdit: boolean
  hasPrev: boolean
  hasNext: boolean
  modelTitle: string
}>()

const emit = defineEmits<{
  close: []
  prev: []
  next: []
  updated: [work: Generation]
  deleted: [id: number]
}>()

const router = useRouter()
const panel = ref<HTMLElement | null>(null)
const confirming = shallowRef(false)
const busy = shallowRef(false)
const error = shallowRef('')

useFocusTrap(panel)

const QUALITY: Record<string, string> = { low: 'низкое', medium: 'среднее', high: 'высокое', auto: 'авто' }
const STATUS: Record<string, string> = { pending: 'в очереди', running: 'рисуется', done: 'готово', error: 'ошибка' }

const done = computed(() => props.work.status === 'done')
const titleId = computed(() => `work-title-${props.work.id}`)

watch(
  () => props.work.id,
  () => {
    confirming.value = false
    error.value = ''
  },
)

function inputLabel(i: Generation['inputs'][number]): string {
  if (i.source_generation_id !== null) return `Работа #${i.source_generation_id}`
  return i.filename ?? `Референс ${i.idx + 1}`
}

async function toggleShared(e: Event): Promise<void> {
  const target = e.target as HTMLInputElement
  const shared = target.checked
  busy.value = true
  error.value = ''
  try {
    const updated = await unwrap(
      api.PATCH('/api/generations/{id}', { params: { path: { id: props.work.id } }, body: { shared } }),
    )
    emit('updated', updated)
  } catch (err) {
    target.checked = !shared
    error.value = err instanceof ApiError ? err.detail : 'Не удалось сохранить'
  } finally {
    busy.value = false
  }
}

async function askDelete(): Promise<void> {
  confirming.value = true
  await nextTick()
  panel.value?.querySelector<HTMLElement>('[data-testid="confirm-delete"]')?.focus()
}

async function cancelDelete(): Promise<void> {
  confirming.value = false
  await nextTick()
  panel.value?.querySelector<HTMLElement>('[data-testid="delete-work"]')?.focus()
}

async function confirmDelete(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await unwrap(api.DELETE('/api/generations/{id}', { params: { path: { id: props.work.id } } }))
    emit('deleted', props.work.id)
  } catch (err) {
    error.value = err instanceof ApiError ? err.detail : 'Не удалось удалить'
    confirming.value = false
  } finally {
    busy.value = false
  }
}

function goGenerate(param: 'ref' | 'repeat'): void {
  void router.push({ name: 'generate', query: { [param]: String(props.work.id) } })
}

function isTyping(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  if (t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement) return true
  return t instanceof HTMLInputElement && t.type !== 'checkbox'
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.preventDefault()
    if (confirming.value) void cancelDelete()
    else emit('close')
  } else if (e.key === 'ArrowLeft' && !isTyping(e.target) && props.hasPrev) {
    e.preventDefault()
    emit('prev')
  } else if (e.key === 'ArrowRight' && !isTyping(e.target) && props.hasNext) {
    e.preventDefault()
    emit('next')
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  document.body.style.overflow = 'hidden'
  panel.value?.focus()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div class="backdrop" data-testid="work-dialog-backdrop" @click.self="emit('close')">
      <div
        ref="panel"
        class="dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        data-testid="work-dialog"
      >
        <header class="head">
          <h2 :id="titleId" class="title">Работа #{{ work.id }}</h2>
          <div class="nav">
            <button
              type="button"
              class="btn btn-ghost"
              :disabled="!hasPrev"
              aria-label="Предыдущая работа"
              data-testid="prev-work"
              @click="emit('prev')"
            >
              ←
            </button>
            <button
              type="button"
              class="btn btn-ghost"
              :disabled="!hasNext"
              aria-label="Следующая работа"
              data-testid="next-work"
              @click="emit('next')"
            >
              →
            </button>
            <button type="button" class="btn btn-ghost" aria-label="Закрыть" data-testid="close-dialog" @click="emit('close')">
              ✕
            </button>
          </div>
        </header>

        <div class="body">
          <div class="result">
            <img v-if="done" :key="work.id" :src="imageUrl(work.id, 'result')" :alt="`Результат работы #${work.id}`" />
            <div v-else class="placeholder" :class="{ failed: work.status === 'error' }">
              {{ work.status === 'error' ? (work.error ?? 'Ошибка генерации') : 'Работа ещё не готова' }}
            </div>
          </div>

          <div class="info">
            <p class="prompt" data-testid="work-prompt">{{ work.prompt }}</p>

            <dl class="meta">
              <dt>Модель</dt>
              <dd>{{ modelTitle }}</dd>
              <dt>Качество</dt>
              <dd>{{ QUALITY[work.quality] ?? work.quality }}</dd>
              <dt>Размер</dt>
              <dd>{{ work.size }}</dd>
              <dt>Формат</dt>
              <dd>{{ work.output_format.toUpperCase() }}</dd>
              <dt>Стоимость</dt>
              <dd data-testid="work-cost">{{ formatUsd(work.cost_micro_usd, 3) }}</dd>
              <dt>Автор</dt>
              <dd data-testid="work-author">{{ work.username }}</dd>
              <dt>Время</dt>
              <dd>{{ formatDateTime(work.created_at) }}</dd>
              <template v-if="!done">
                <dt>Статус</dt>
                <dd>{{ STATUS[work.status] }}</dd>
              </template>
            </dl>

            <section v-if="work.inputs.length" class="refs" aria-label="Референсы">
              <h3>Референсы ({{ work.inputs.length }})</h3>
              <ul class="ref-list" data-testid="work-inputs">
                <li v-for="i in work.inputs" :key="i.idx">
                  <img :src="imageUrl(work.id, 'input', { idx: i.idx })" :alt="inputLabel(i)" loading="lazy" />
                  <span class="ref-label">{{ inputLabel(i) }}</span>
                </li>
              </ul>
            </section>

            <div class="actions">
              <a
                v-if="done"
                class="btn btn-primary"
                :href="imageUrl(work.id, 'result', { download: true })"
                :download="`design-${work.id}.${work.output_format === 'jpeg' ? 'jpg' : work.output_format}`"
                data-testid="download-work"
              >
                Скачать
              </a>
              <button v-if="done" type="button" class="btn" data-testid="edit-further" @click="goGenerate('ref')">
                Править дальше
              </button>
              <button type="button" class="btn" data-testid="repeat-work" @click="goGenerate('repeat')">Повторить</button>
            </div>

            <template v-if="canEdit">
              <label class="switch">
                <input
                  type="checkbox"
                  :checked="work.shared"
                  :disabled="busy"
                  data-testid="shared-toggle"
                  @change="toggleShared"
                />
                Видна всем
              </label>

              <div v-if="!confirming" class="danger-zone">
                <button type="button" class="btn btn-danger" :disabled="busy" data-testid="delete-work" @click="askDelete">
                  Удалить работу
                </button>
              </div>
              <div v-else class="danger-zone confirm" role="alertdialog" aria-label="Подтверждение удаления">
                <span>Удалить работу #{{ work.id }} безвозвратно?</span>
                <div class="confirm-buttons">
                  <button
                    type="button"
                    class="btn btn-danger"
                    :disabled="busy"
                    data-testid="confirm-delete"
                    @click="confirmDelete"
                  >
                    Да, удалить
                  </button>
                  <button type="button" class="btn" :disabled="busy" data-testid="cancel-delete" @click="cancelDelete">
                    Отмена
                  </button>
                </div>
              </div>
            </template>

            <p v-if="error" class="error" role="alert" data-testid="dialog-error">{{ error }}</p>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgb(0 0 0 / 55%);
}

.dialog {
  width: 100%;
  max-width: 1040px;
  max-height: 100%;
  overflow: auto;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.dialog:focus {
  outline: none;
}

.head {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 8px 8px 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.title {
  margin: 0;
  font-size: 17px;
}

.nav {
  display: flex;
  gap: 2px;
}

.body {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--gap);
  padding: var(--gap);
}

.result img {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 6px;
  background: var(--surface-2);
}

.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 1;
  padding: 16px;
  text-align: center;
  color: var(--text-muted);
  background: var(--surface-2);
  border-radius: 6px;
}

.placeholder.failed {
  color: var(--danger);
  background: var(--danger-soft);
}

.info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.prompt {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.meta {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px 12px;
  margin: 0;
  font-size: 14px;
}

.meta dt {
  color: var(--text-muted);
}

.meta dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.refs h3 {
  font-size: 14px;
  margin-bottom: 6px;
}

.ref-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.ref-list img {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: 4px;
  background: var(--surface-2);
}

.ref-label {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.switch input {
  width: 18px;
  height: 18px;
  accent-color: var(--accent);
}

.danger-zone {
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.confirm {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--danger);
}

.confirm-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 720px) {
  .backdrop {
    padding: 0;
  }

  .dialog {
    height: 100%;
    border-radius: 0;
  }

  .body {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
