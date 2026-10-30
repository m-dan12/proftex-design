<script setup lang="ts">
// Галереи «Мои» и «Общая»: сетка превью с подгрузкой при прокрутке, фильтр по автору,
// диалог работы. Адрес: /gallery?tab=mine|shared&id=ID.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, unwrap, type Generation } from '@/api/client'
import { auth } from '@/stores/auth'
import WorkCard from './WorkCard.vue'
import WorkDialog from './WorkDialog.vue'
import { useGalleryFeed, type GalleryScope } from './useGalleryFeed'

const route = useRoute()
const router = useRouter()
const feed = useGalleryFeed()
const { items, hasMore, loading, loaded, error, authors } = feed

const tab = computed<GalleryScope>(() => (route.query.tab === 'shared' ? 'shared' : 'mine'))
const authorId = shallowRef<number | null>(null)
const openId = computed<number | null>(() => {
  const n = Number(route.query.id)
  return Number.isInteger(n) && n > 0 ? n : null
})

/** Работа из ссылки ?id=, которой нет в загруженной ленте. */
const standalone = shallowRef<Generation | null>(null)
const dialogError = shallowRef('')
const modelTitles = ref(new Map<string, string>())

const current = computed<Generation | null>(() => {
  const id = openId.value
  if (id === null) return null
  return items.value.find((g) => g.id === id) ?? (standalone.value?.id === id ? standalone.value : null)
})
const index = computed(() => (current.value ? items.value.findIndex((g) => g.id === current.value!.id) : -1))
const hasPrev = computed(() => index.value > 0)
const hasNext = computed(() => index.value >= 0 && (index.value < items.value.length - 1 || hasMore.value))
const canEdit = computed(() => {
  const me = auth.state.user
  return !!me && !!current.value && (me.is_admin || current.value.user_id === me.id)
})

const authorOptions = computed(() =>
  [...authors.value.entries()].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name)),
)
const skeletons = computed(() => loading.value && !loaded.value)
const empty = computed(() => loaded.value && !items.value.length && !error.value)

// --- вкладки и фильтр ---

function selectTab(next: GalleryScope): void {
  if (next === tab.value) return
  void router.replace({ query: { ...route.query, tab: next, id: undefined } })
}

function onTabKeydown(e: KeyboardEvent): void {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  e.preventDefault()
  const next: GalleryScope = tab.value === 'mine' ? 'shared' : 'mine'
  selectTab(next)
  void nextTick(() => document.getElementById(`gallery-tab-${next}`)?.focus())
}

function onAuthorChange(e: Event): void {
  const v = (e.target as HTMLSelectElement).value
  authorId.value = v ? Number(v) : null
  void feed.reload('shared', authorId.value)
}

watch(
  tab,
  (t) => {
    authorId.value = null
    void feed.reload(t, null)
  },
  { immediate: true },
)

// --- подгрузка при прокрутке ---

const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

onMounted(() => {
  if (typeof IntersectionObserver !== 'undefined') {
    observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) void feed.loadMore()
      },
      { rootMargin: '600px 0px' },
    )
    watch(
      sentinel,
      (el, old) => {
        if (old) observer?.unobserve(old)
        if (el) observer?.observe(el)
      },
      { immediate: true },
    )
  }
  unwrap(api.GET('/api/models'))
    .then((res) => {
      modelTitles.value = new Map(res.models.map((m) => [m.id, m.title]))
    })
    .catch(() => {
      // без названий покажем id модели
    })
})

onBeforeUnmount(() => observer?.disconnect())

// --- диалог ---

function openWork(id: number): void {
  void router.replace({ query: { ...route.query, id: String(id) } })
}

async function closeDialog(): Promise<void> {
  const id = openId.value
  await router.replace({ query: { ...route.query, id: undefined } })
  await nextTick()
  const card = document.querySelector<HTMLElement>(`[data-work-id="${id}"] button`)
  ;(card ?? document.getElementById(`gallery-tab-${tab.value}`))?.focus()
}

async function step(delta: 1 | -1): Promise<void> {
  let i = index.value + delta
  if (i >= items.value.length && hasMore.value) await feed.loadMore()
  i = Math.max(0, Math.min(i, items.value.length - 1))
  const next = items.value[i]
  if (next) openWork(next.id)
}

function onUpdated(g: Generation): void {
  feed.replace(g)
  if (standalone.value?.id === g.id) standalone.value = g
}

async function onDeleted(id: number): Promise<void> {
  const i = items.value.findIndex((g) => g.id === id)
  feed.remove(id)
  if (standalone.value?.id === id) standalone.value = null
  await router.replace({ query: { ...route.query, id: undefined } })
  await nextTick()
  const neighbour = items.value[Math.min(Math.max(i, 0), items.value.length - 1)]
  const card = neighbour ? document.querySelector<HTMLElement>(`[data-work-id="${neighbour.id}"] button`) : null
  ;(card ?? document.getElementById(`gallery-tab-${tab.value}`))?.focus()
}

// Ссылка ?id= на работу, которой нет в ленте (другая страница или чужая общая): грузим отдельно.
watch(
  [openId, loaded],
  async ([id, isLoaded]) => {
    dialogError.value = ''
    if (id === null || !isLoaded || items.value.some((g) => g.id === id) || standalone.value?.id === id) return
    try {
      standalone.value = await unwrap(api.GET('/api/generations/{id}', { params: { path: { id } } }))
    } catch (e) {
      dialogError.value = e instanceof Error ? `Работа #${id}: ${e.message}` : 'Работа не найдена'
      void router.replace({ query: { ...route.query, id: undefined } })
    }
  },
  { immediate: true },
)
</script>

<template>
  <section class="page gallery">
    <h1>Галерея</h1>

    <div class="toolbar">
      <div class="tabs" role="tablist" aria-label="Галереи">
        <button
          v-for="t in [
            { id: 'mine', label: 'Мои' },
            { id: 'shared', label: 'Общая' },
          ] as const"
          :id="`gallery-tab-${t.id}`"
          :key="t.id"
          type="button"
          role="tab"
          class="tab"
          :class="{ active: tab === t.id }"
          :aria-selected="tab === t.id"
          :tabindex="tab === t.id ? 0 : -1"
          aria-controls="gallery-panel"
          :data-testid="`tab-${t.id}`"
          @click="selectTab(t.id)"
          @keydown="onTabKeydown"
        >
          {{ t.label }}
        </button>
      </div>

      <div v-if="tab === 'shared'" class="filter">
        <label for="gallery-author" class="muted">Автор</label>
        <select
          id="gallery-author"
          class="select"
          :value="authorId ?? ''"
          data-testid="author-filter"
          @change="onAuthorChange"
        >
          <option value="">Все</option>
          <option v-for="a in authorOptions" :key="a.id" :value="a.id">{{ a.name }}</option>
        </select>
      </div>
    </div>

    <div id="gallery-panel" role="tabpanel" :aria-labelledby="`gallery-tab-${tab}`" :aria-busy="loading">
      <p v-if="dialogError" class="error" role="alert" data-testid="open-error">{{ dialogError }}</p>

      <ul v-if="skeletons" class="grid" aria-hidden="true" data-testid="skeletons">
        <li v-for="n in 8" :key="n" class="skeleton" />
      </ul>

      <div v-else-if="empty" class="empty card" data-testid="empty-state">
        <template v-if="authorId !== null">
          <p>У этого автора нет общих работ.</p>
        </template>
        <template v-else>
          <p>Пока нет работ</p>
          <RouterLink :to="{ name: 'generate' }" class="btn btn-primary" data-testid="create-work">
            Создать работу
          </RouterLink>
        </template>
      </div>

      <ul v-else class="grid" data-testid="gallery-grid">
        <WorkCard
          v-for="g in items"
          :key="g.id"
          :work="g"
          :show-author="tab === 'shared'"
          @open="openWork(g.id)"
        />
      </ul>

      <p v-if="error" class="error" role="alert" data-testid="gallery-error">
        {{ error }}
        <button type="button" class="btn btn-ghost" @click="loaded ? feed.loadMore() : feed.reload()">
          Повторить попытку
        </button>
      </p>

      <div v-if="hasMore && !error" ref="sentinel" class="more">
        <button type="button" class="btn" :disabled="loading" data-testid="load-more" @click="feed.loadMore()">
          {{ loading ? 'Загрузка…' : 'Показать ещё' }}
        </button>
      </div>
    </div>

    <WorkDialog
      v-if="current"
      :work="current"
      :can-edit="canEdit"
      :has-prev="hasPrev"
      :has-next="hasNext"
      :model-title="modelTitles.get(current.model) ?? current.model"
      @close="closeDialog"
      @prev="step(-1)"
      @next="step(1)"
      @updated="onUpdated"
      @deleted="onDeleted"
    />
  </section>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  margin-bottom: var(--gap);
}

.tabs {
  display: inline-flex;
  padding: 3px;
  gap: 2px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.tab {
  min-height: 32px;
  padding: 4px 16px;
  font: inherit;
  color: var(--text-muted);
  background: transparent;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.tab.active {
  color: var(--text);
  background: var(--surface);
  box-shadow: var(--shadow);
}

.filter {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.filter .select {
  width: auto;
  max-width: 220px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

@media (min-width: 720px) {
  .grid {
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  }
}

.skeleton {
  aspect-ratio: 1;
  border-radius: var(--radius);
  background: linear-gradient(90deg, var(--surface-2) 25%, var(--border) 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.2s ease-in-out infinite;
}

@keyframes shimmer {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: -200% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton {
    animation: none;
  }
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px var(--gap);
  text-align: center;
}

.empty p {
  margin: 0;
  font-size: 17px;
}

.more {
  display: flex;
  justify-content: center;
  padding: var(--gap) 0;
}

.error {
  margin: 12px 0;
}
</style>
