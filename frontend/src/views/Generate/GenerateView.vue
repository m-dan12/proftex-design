<script setup lang="ts">
// Экран генерации (T11): форма, референсы, запуск и текущие генерации с опросом статусов.
// Параметры адреса: ?ref=ID — работа становится референсом («Править дальше» из галереи),
// ?repeat=ID — форма заполняется промптом и настройками работы.
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, api, createGeneration, unwrap, type Generation, type ModelInfo, type ModelsResponse } from '@/api/client'
import { formatUsd } from '@/utils/format'
import GalleryPicker from './GalleryPicker.vue'
import ReferenceZone from './ReferenceZone.vue'
import ResultBatch from './ResultBatch.vue'
import { MAX_REFS, checkFiles, fileRef, releaseRef, workRef, type RefItem } from './references'
import { addBatch, batches, createPoller, fetchGeneration } from './tracker'

type OutputFormat = Generation['output_format']

const MAX_PROMPT = 4000
const FORMAT_TEXT: Record<OutputFormat, string> = { jpeg: 'JPEG', png: 'PNG', webp: 'WebP' }
const QUALITY_TEXT: Record<string, string> = { low: 'низкое', medium: 'среднее', high: 'высокое', auto: 'авто' }

const route = useRoute()
const router = useRouter()

const models = ref<ModelInfo[]>([])
const mode = ref<ModelsResponse['mode']>('openai')
const loadError = ref('')

const form = reactive({
  prompt: '',
  model: '',
  quality: '',
  size: '',
  output_format: 'jpeg' as OutputFormat,
  n: 1,
  /** «Сохранять детали референсов»: input_fidelity=high (по умолчанию) или low. */
  keepDetails: true,
  shared: true,
})
const refs = ref<RefItem[]>([])
/** Работа, от которой идёт «Править дальше» (parent_id), — всегда среди референсов. */
const parentId = ref<number | null>(null)
const refErrors = ref<string[]>([])
const formError = ref('')
const busy = ref(false)
const picking = ref(false)

const model = computed(() => models.value.find((m) => m.id === form.model))
const promptLength = computed(() => form.prompt.length)
const variantOptions = computed(() => Array.from({ length: model.value?.max_n ?? 1 }, (_, i) => i + 1))
/** Примерная цена: запасная цена картинки при выбранном качестве × число вариантов. */
const price = computed(() => (model.value?.fallback_per_image_micro_usd[form.quality] ?? 0) * form.n)
const selectedWorks = computed(() =>
  refs.value.flatMap((r) => (r.kind === 'work' ? [r.generationId] : [])),
)

/** Подгоняет поля под выбранную модель: то, что она не поддерживает, сбрасывается на её значения. */
function normalize(): void {
  const m = model.value
  if (!m) return
  if (!m.qualities.includes(form.quality)) form.quality = m.default_quality
  if (!m.sizes.includes(form.size)) form.size = m.sizes[0] ?? ''
  if (!m.output_formats.includes(form.output_format)) {
    form.output_format = m.output_formats.includes('jpeg') ? 'jpeg' : (m.output_formats[0] ?? 'jpeg')
  }
  if (form.n > m.max_n) form.n = m.max_n
  if (form.n < 1) form.n = 1
}

async function loadModels(): Promise<void> {
  try {
    const res = await unwrap(api.GET('/api/models'))
    models.value = res.models
    mode.value = res.mode
    form.model = res.models.some((m) => m.id === res.default_model) ? res.default_model : (res.models[0]?.id ?? '')
    normalize()
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить список моделей'
  }
}

// --- референсы ---

function addFiles(files: File[]): void {
  const { accepted, errors } = checkFiles(files, refs.value.length)
  refErrors.value = errors
  refs.value.push(...accepted.map(fileRef))
}

function addWork(id: number, asParent = false): boolean {
  refErrors.value = []
  if (!refs.value.some((r) => r.kind === 'work' && r.generationId === id)) {
    if (refs.value.length >= MAX_REFS) {
      refErrors.value = [`Не больше ${MAX_REFS} референсов — уберите лишние`]
      return false
    }
    refs.value.push(workRef(id))
  }
  if (asParent) parentId.value = id
  return true
}

function removeRef(key: string): void {
  const item = refs.value.find((r) => r.key === key)
  if (!item) return
  releaseRef(item)
  refs.value = refs.value.filter((r) => r !== item)
  if (item.kind === 'work' && item.generationId === parentId.value) parentId.value = null
  refErrors.value = []
}

function onPaste(e: ClipboardEvent): void {
  const files = [...(e.clipboardData?.files ?? [])]
  if (!files.length) return
  e.preventDefault()
  addFiles(files)
}

// --- «Править дальше» и «Повторить» ---

const formEl = ref<HTMLElement | null>(null)

function toForm(): void {
  formEl.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
}

function editFurther(g: Generation): void {
  if (addWork(g.id, true)) toForm()
}

function repeat(g: Generation): void {
  form.prompt = g.prompt
  if (models.value.some((m) => m.id === g.model)) form.model = g.model
  const m = model.value
  if (m?.qualities.includes(g.quality)) form.quality = g.quality
  if (m?.sizes.includes(g.size)) form.size = g.size
  if (m?.output_formats.includes(g.output_format)) form.output_format = g.output_format
  form.keepDetails = g.input_fidelity !== 'low'
  form.shared = g.shared
  normalize()
  formError.value = ''
  toForm()
}

/** ?ref=ID и ?repeat=ID: применяем один раз и убираем из адреса, чтобы обновление страницы не повторяло. */
async function applyQuery(): Promise<void> {
  if (route.name !== 'generate') return
  const refId = Number(route.query.ref)
  const repeatId = Number(route.query.repeat)
  if (!refId && !repeatId) return
  void router.replace({ query: {} })
  try {
    if (repeatId) repeat(await fetchGeneration(repeatId))
    if (refId) addWork((await fetchGeneration(refId)).id, true)
  } catch (e) {
    formError.value = e instanceof ApiError && e.status === 404 ? 'Работа не найдена' : 'Не удалось открыть работу'
  }
}

// --- запуск ---

const poller = createPoller(batches)

function validate(): string {
  if (!form.prompt.trim()) return 'Введите промпт'
  if (form.prompt.length > MAX_PROMPT) return `Промпт длиннее ${MAX_PROMPT} символов`
  if (!model.value) return 'Выберите модель'
  if (refs.value.length > MAX_REFS) return `Не больше ${MAX_REFS} референсов`
  return ''
}

function buildForm(): FormData {
  const fd = new FormData()
  fd.append('prompt', form.prompt)
  fd.append('model', form.model)
  fd.append('quality', form.quality)
  fd.append('size', form.size)
  fd.append('n', String(form.n))
  fd.append('output_format', form.output_format)
  fd.append('shared', String(form.shared))
  if (model.value?.supports_input_fidelity && refs.value.length) {
    fd.append('input_fidelity', form.keepDetails ? 'high' : 'low')
  }
  for (const r of refs.value) if (r.kind === 'work') fd.append('source_ids', String(r.generationId))
  if (parentId.value !== null && selectedWorks.value.includes(parentId.value)) {
    fd.append('parent_id', String(parentId.value))
  }
  for (const r of refs.value) if (r.kind === 'file') fd.append('files', r.file, r.file.name)
  return fd
}

async function submit(): Promise<void> {
  if (busy.value) return
  formError.value = validate()
  if (formError.value) return
  busy.value = true
  try {
    const created = await createGeneration(buildForm())
    addBatch(batches, created, form.prompt)
    poller.poke()
  } catch (e) {
    formError.value = e instanceof ApiError ? e.detail : 'Сервер недоступен, попробуйте позже'
  } finally {
    busy.value = false
  }
}

watch(() => form.model, normalize)

watch(
  () => route.query,
  () => void applyQuery(),
)

onMounted(async () => {
  document.addEventListener('paste', onPaste)
  poller.start()
  await loadModels()
  await applyQuery()
})

onUnmounted(() => {
  poller.stop()
  document.removeEventListener('paste', onPaste)
  refs.value.forEach(releaseRef)
})
</script>

<template>
  <section class="page generate">
    <h1>Создать</h1>
    <p v-if="mode === 'mock'" class="mock-note" data-testid="mock-mode">
      Тестовый режим: OpenAI не вызывается, вместо картинок — заглушки
    </p>
    <p v-if="loadError" class="error">{{ loadError }}</p>

    <div class="layout">
      <form ref="formEl" class="card gen-form" novalidate data-testid="generate-form" @submit.prevent="submit">
        <div class="field">
          <label for="gen-prompt">Промпт</label>
          <textarea
            id="gen-prompt"
            v-model="form.prompt"
            class="textarea"
            rows="5"
            placeholder="Что нарисовать или что поменять на референсах"
          ></textarea>
          <span class="counter" :class="{ over: promptLength > MAX_PROMPT }" data-testid="prompt-counter">
            {{ promptLength }} / {{ MAX_PROMPT }}
          </span>
        </div>

        <div class="field">
          <span class="label">Референсы</span>
          <ReferenceZone :items="refs" @files="addFiles" @remove="removeRef" @pick="picking = true" />
          <p v-for="(msg, i) in refErrors" :key="i" class="error ref-error" data-testid="ref-error">{{ msg }}</p>
          <p v-if="parentId !== null" class="muted small" data-testid="parent-note">
            Правка работы №{{ parentId }}
          </p>
        </div>

        <div class="grid">
          <div class="field">
            <label for="gen-model">Модель</label>
            <select id="gen-model" v-model="form.model" class="select">
              <option v-for="m in models" :key="m.id" :value="m.id">{{ m.title }}</option>
            </select>
          </div>
          <div class="field">
            <label for="gen-quality">Качество</label>
            <select id="gen-quality" v-model="form.quality" class="select">
              <option v-for="q in model?.qualities ?? []" :key="q" :value="q">{{ QUALITY_TEXT[q] ?? q }}</option>
            </select>
          </div>
          <div class="field">
            <label for="gen-size">Размер</label>
            <select id="gen-size" v-model="form.size" class="select">
              <option v-for="s in model?.sizes ?? []" :key="s" :value="s">{{ s === 'auto' ? 'авто' : s }}</option>
            </select>
          </div>
          <div class="field">
            <label for="gen-format">Формат</label>
            <select id="gen-format" v-model="form.output_format" class="select">
              <option v-for="f in model?.output_formats ?? []" :key="f" :value="f">{{ FORMAT_TEXT[f] }}</option>
            </select>
          </div>
          <div v-if="variantOptions.length > 1" class="field">
            <label for="gen-n">Вариантов</label>
            <select id="gen-n" v-model.number="form.n" class="select">
              <option v-for="k in variantOptions" :key="k" :value="k">{{ k }}</option>
            </select>
          </div>
        </div>

        <label v-if="model?.supports_input_fidelity" class="check" data-testid="fidelity">
          <input id="gen-fidelity" v-model="form.keepDetails" type="checkbox" />
          Сохранять детали референсов
        </label>
        <label class="check">
          <input id="gen-shared" v-model="form.shared" type="checkbox" />
          Видна всем
        </label>

        <p v-if="formError" class="error" role="alert" data-testid="form-error">{{ formError }}</p>

        <div class="submit-row">
          <button type="submit" class="btn btn-primary" :disabled="busy || !model">
            {{ busy ? 'Отправляю…' : 'Сгенерировать' }}
          </button>
          <span v-if="model" class="muted price" data-testid="price">≈ {{ formatUsd(price) }}</span>
        </div>
      </form>

      <div class="results" data-testid="results">
        <h2>Текущие генерации</h2>
        <p v-if="!batches.length" class="muted">Здесь появятся запуски и их результаты. Можно запускать несколько подряд.</p>
        <ResultBatch v-for="b in batches" :key="b.batchId" :batch="b" @edit="editFurther" @repeat="repeat" />
      </div>
    </div>

    <GalleryPicker
      v-if="picking"
      :selected="selectedWorks"
      :left="MAX_REFS - refs.length"
      @pick="(g) => addWork(g.id)"
      @close="picking = false"
    />
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--gap);
  align-items: start;
}

@media (min-width: 900px) {
  .layout {
    grid-template-columns: minmax(0, 420px) minmax(0, 1fr);
  }
}

.gen-form {
  min-width: 0;
  scroll-margin-top: calc(var(--header-h) + 8px);
}

.label {
  font-size: 13px;
  color: var(--text-muted);
}

.counter {
  align-self: flex-end;
  font-size: 12px;
  color: var(--text-muted);
}

.counter.over {
  color: var(--danger);
  font-weight: 600;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.check {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  cursor: pointer;
}

.ref-error {
  margin: 6px 0 0;
  font-size: 14px;
}

.small {
  margin: 6px 0 0;
  font-size: 13px;
}

.submit-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}

.results {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
}

.results h2 {
  margin: 0;
  font-size: 18px;
}

.mock-note {
  padding: 6px 12px;
  color: var(--warning);
  background: var(--surface-2);
  border-radius: 6px;
  font-size: 14px;
}

.textarea {
  resize: vertical;
}
</style>
