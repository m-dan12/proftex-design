// Список запусков на экране генерации и опрос их статусов.
// Опрос: каждые 2 с, только пока есть незавершённые работы, на паузе при скрытой вкладке,
// останавливается при уходе со страницы (stop() из onUnmounted).
import { ref, type Ref } from 'vue'
import { ApiError, api, unwrap, type Generation, type GenerationCreated } from '@/api/client'

export const POLL_INTERVAL_MS = 2000

export interface Batch {
  batchId: string
  ids: number[]
  /** Промпт запуска — подпись, пока работы ещё не пришли с сервера. */
  prompt: string
  items: Record<number, Generation | undefined>
  /** Работы, которых больше нет на сервере (удалили). */
  gone: number[]
}

export const isFinal = (g: Generation | undefined): boolean => g?.status === 'done' || g?.status === 'error'

/** Запуски живут, пока открыта вкладка: при возврате на экран список и опрос восстанавливаются. */
export const batches: Ref<Batch[]> = ref([])

export function resetBatches(): void {
  batches.value = []
}

export function addBatch(list: Ref<Batch[]>, created: GenerationCreated, prompt: string): Batch {
  const batch: Batch = { batchId: created.batch_id, ids: [...created.ids], prompt, items: {}, gone: [] }
  list.value.unshift(batch)
  return list.value[0]!
}

export const fetchGeneration = (id: number): Promise<Generation> =>
  unwrap(api.GET('/api/generations/{id}', { params: { path: { id } } }))

export interface Poller {
  start(): void
  stop(): void
  /** Опросить сейчас, не дожидаясь интервала (после нового запуска). */
  poke(): void
}

export function createPoller(
  list: Ref<Batch[]>,
  fetchOne: (id: number) => Promise<Generation> = fetchGeneration,
  interval = POLL_INTERVAL_MS,
): Poller {
  let timer: ReturnType<typeof setTimeout> | null = null
  let running = false
  let inflight = false

  const hidden = () => typeof document !== 'undefined' && document.hidden

  function pending(): Array<[Batch, number]> {
    return list.value.flatMap((b) =>
      b.ids.filter((id) => !b.gone.includes(id) && !isFinal(b.items[id])).map((id): [Batch, number] => [b, id]),
    )
  }

  function clear(): void {
    if (timer !== null) clearTimeout(timer)
    timer = null
  }

  function schedule(): void {
    clear()
    if (!running || hidden() || pending().length === 0) return
    timer = setTimeout(() => void tick(), interval)
  }

  async function tick(): Promise<void> {
    timer = null
    if (!running || inflight) return
    const todo = pending()
    if (!todo.length) return
    inflight = true
    await Promise.all(
      todo.map(async ([batch, id]) => {
        try {
          batch.items[id] = await fetchOne(id)
        } catch (e) {
          if (e instanceof ApiError && e.status === 404) batch.gone.push(id)
          // сеть и прочие сбои — повторим на следующем круге
        }
      }),
    )
    inflight = false
    schedule()
  }

  function poke(): void {
    if (!running || hidden() || inflight) return
    clear()
    void tick()
  }

  function onVisibility(): void {
    if (hidden()) clear()
    else poke()
  }

  return {
    start() {
      if (running) return
      running = true
      document.addEventListener('visibilitychange', onVisibility)
      poke()
    },
    stop() {
      running = false
      clear()
      document.removeEventListener('visibilitychange', onVisibility)
    },
    poke,
  }
}
