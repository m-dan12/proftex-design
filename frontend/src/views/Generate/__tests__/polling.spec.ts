// Показатель 5 карточки T11: опрос статусов каждые 2 с останавливается при done, error,
// при скрытой вкладке (и возобновляется) и при уходе со страницы. Таймеры фейковые.
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { Generation, GenerationStatus } from '@/api/client'
import { ApiError } from '@/api/client'
import { db, saveSession } from '@/mocks/db'
import { server } from '@/mocks/node'
import { mountApp } from '@/__tests__/helpers'
import { addBatch, createPoller, POLL_INTERVAL_MS, resetBatches, type Batch } from '../tracker'

function gen(id: number, status: GenerationStatus, error: string | null = null): Generation {
  return { ...db.generations[0]!, id, status, error }
}

/** Заглушка GET /api/generations/{id}: по каждому id отдаёт статусы по очереди, последний повторяет. */
function scripted(plan: Record<number, Array<GenerationStatus | 'gone'>>) {
  const calls: number[] = []
  const fetchOne = vi.fn(async (id: number) => {
    calls.push(id)
    const seq = plan[id]!
    const status = seq.length > 1 ? seq.shift()! : seq[0]!
    if (status === 'gone') throw new ApiError(404, 'Работа не найдена')
    return gen(id, status, status === 'error' ? 'Запрос отклонён модерацией' : null)
  })
  return { fetchOne, calls }
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('опрос статусов (createPoller)', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    setHidden(false)
  })

  it('опрашивает каждые 2 с и останавливается, когда все варианты done', async () => {
    const list = ref<Batch[]>([])
    const { fetchOne, calls } = scripted({ 10: ['pending', 'running', 'done'], 11: ['running', 'done'] })
    const poller = createPoller(list, fetchOne)
    poller.start()
    expect(fetchOne).not.toHaveBeenCalled() // пока нечего опрашивать

    addBatch(list, { batch_id: 'b1', ids: [10, 11] }, 'промпт')
    poller.poke()
    await vi.advanceTimersByTimeAsync(0)
    expect(calls).toEqual([10, 11]) // сразу после запуска
    expect(list.value[0]!.items[10]!.status).toBe('pending')

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS - 1)
    expect(calls).toHaveLength(2) // раньше 2 с не опрашивает
    await vi.advanceTimersByTimeAsync(1)
    expect(calls).toEqual([10, 11, 10, 11]) // 11 стал done
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(calls).toEqual([10, 11, 10, 11, 10]) // 11 больше не спрашиваем, 10 стал done

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 10)
    expect(calls).toHaveLength(5)
    expect(vi.getTimerCount()).toBe(0)
    poller.stop()
  })

  it('останавливается при error', async () => {
    const list = ref<Batch[]>([])
    const { fetchOne } = scripted({ 20: ['running', 'error'] })
    const poller = createPoller(list, fetchOne)
    poller.start()
    addBatch(list, { batch_id: 'b2', ids: [20] }, 'промпт')
    poller.poke()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(fetchOne).toHaveBeenCalledTimes(2)
    expect(list.value[0]!.items[20]!.error).toBe('Запрос отклонён модерацией')
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 10)
    expect(fetchOne).toHaveBeenCalledTimes(2)
    expect(vi.getTimerCount()).toBe(0)
    poller.stop()
  })

  it('удалённую работу (404) больше не опрашивает', async () => {
    const list = ref<Batch[]>([])
    const { fetchOne } = scripted({ 30: ['gone'] })
    const poller = createPoller(list, fetchOne)
    poller.start()
    addBatch(list, { batch_id: 'b3', ids: [30] }, 'промпт')
    poller.poke()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)
    expect(fetchOne).toHaveBeenCalledTimes(1)
    expect(list.value[0]!.gone).toEqual([30])
    poller.stop()
  })

  it('пауза при скрытой вкладке и продолжение при возврате', async () => {
    const list = ref<Batch[]>([])
    const { fetchOne } = scripted({ 40: ['running'] })
    const poller = createPoller(list, fetchOne)
    poller.start()
    addBatch(list, { batch_id: 'b4', ids: [40] }, 'промпт')
    poller.poke()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchOne).toHaveBeenCalledTimes(1)

    setHidden(true)
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)
    expect(fetchOne).toHaveBeenCalledTimes(1)

    setHidden(false)
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchOne).toHaveBeenCalledTimes(2) // сразу при возврате
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(fetchOne).toHaveBeenCalledTimes(3)
    poller.stop()
  })

  it('stop() прекращает опрос и снимает таймер', async () => {
    const list = ref<Batch[]>([])
    const { fetchOne } = scripted({ 50: ['running'] })
    const poller = createPoller(list, fetchOne)
    poller.start()
    addBatch(list, { batch_id: 'b5', ids: [50] }, 'промпт')
    poller.poke()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(fetchOne).toHaveBeenCalledTimes(2)
    poller.stop()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 10)
    expect(fetchOne).toHaveBeenCalledTimes(2)
    setHidden(false) // и возврат во вкладку не будит остановленный опрос
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(fetchOne).toHaveBeenCalledTimes(2)
  })
})

describe('опрос на экране генерации', () => {
  beforeEach(() => {
    saveSession(2)
    resetBatches()
  })
  afterEach(() => vi.useRealTimers())

  it('уход со страницы останавливает опрос, возврат продолжает', async () => {
    // одна незавершённая работа, как будто её запустили на экране
    const id = db.generations[0]!.id
    const { batches } = await import('../tracker')
    addBatch(batches, { batch_id: 'b-view', ids: [id] }, 'промпт')

    let polls = 0
    server.use(
      // работа всё время «рисуется»
      http.get('*/api/generations/:id', ({ params }) => {
        polls += 1
        return HttpResponse.json(gen(Number(params.id), 'running'))
      }),
    )
    // фейковые таймеры, но с ходом реального времени — иначе не дождаться ленивых компонентов маршрутов
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true })
    const { wrapper, router } = await mountApp('/generate')
    expect(polls).toBe(1) // опрос при открытии экрана

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(polls).toBe(2)

    await router.push('/gallery')
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.find('[data-testid="generate-form"]').exists()).toBe(false)
    const after = polls
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)
    expect(polls).toBe(after)

    await router.push('/generate')
    await vi.advanceTimersByTimeAsync(0)
    await vi.waitFor(() => expect(polls).toBe(after + 1))
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)
    expect(polls).toBe(after + 1)
  })
})
