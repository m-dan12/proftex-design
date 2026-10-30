// Лента галереи: курсорная пагинация GET /api/generations без дублей.
import { computed, ref, shallowRef } from 'vue'
import { api, unwrap, type Generation } from '@/api/client'

export type GalleryScope = 'mine' | 'shared'

export const PAGE_SIZE = 50

export function useGalleryFeed() {
  const items = ref<Generation[]>([])
  const nextCursor = shallowRef<string | null>(null)
  const loading = shallowRef(false)
  const loaded = shallowRef(false)
  const error = shallowRef('')
  /** Авторы, встреченные в «Общей»: список для фильтра (список пользователей не-админу недоступен). */
  const authors = ref(new Map<number, string>())

  let scope: GalleryScope = 'mine'
  let authorId: number | null = null
  // Номер запроса: ответ устаревшего запроса (после смены вкладки или фильтра) отбрасывается.
  let token = 0

  const hasMore = computed(() => nextCursor.value !== null)

  async function fetchPage(cursor: string | null): Promise<void> {
    const my = ++token
    loading.value = true
    error.value = ''
    try {
      const page = await unwrap(
        api.GET('/api/generations', {
          params: {
            query: {
              scope,
              limit: PAGE_SIZE,
              ...(cursor ? { cursor } : {}),
              ...(authorId !== null && scope === 'shared' ? { author_id: authorId } : {}),
            },
          },
        }),
      )
      if (my !== token) return
      const seen = new Set(cursor ? items.value.map((g) => g.id) : [])
      const fresh = page.items.filter((g) => !seen.has(g.id))
      items.value = cursor ? [...items.value, ...fresh] : fresh
      nextCursor.value = page.next_cursor
      if (scope === 'shared') for (const g of page.items) authors.value.set(g.user_id, g.username)
      loaded.value = true
    } catch (e) {
      if (my !== token) return
      error.value = e instanceof Error ? e.message : 'Не удалось загрузить работы'
    } finally {
      if (my === token) loading.value = false
    }
  }

  /** Сбрасывает ленту и грузит первую страницу. */
  function reload(nextScope: GalleryScope = scope, nextAuthor: number | null = authorId): Promise<void> {
    scope = nextScope
    authorId = nextAuthor
    items.value = []
    nextCursor.value = null
    loaded.value = false
    return fetchPage(null)
  }

  /** Следующая страница; повторный вызов во время загрузки ничего не делает. */
  function loadMore(): Promise<void> {
    if (loading.value || !nextCursor.value) return Promise.resolve()
    return fetchPage(nextCursor.value)
  }

  function replace(g: Generation): void {
    items.value = items.value.map((x) => (x.id === g.id ? g : x))
  }

  function remove(id: number): void {
    items.value = items.value.filter((x) => x.id !== id)
  }

  return { items, hasMore, loading, loaded, error, authors, reload, loadMore, replace, remove }
}
