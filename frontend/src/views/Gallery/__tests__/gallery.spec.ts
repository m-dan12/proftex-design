// Показатели 1, 2, 4, 5, 7 карточки T12 (vitest на MSW-моках) и проверки диалога.
import { http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Generation } from '@/api/client'
import { db, MOCK_ACCOUNTS } from '@/mocks/db'
import { server } from '@/mocks/node'
import { auth } from '@/stores/auth'
import { mountApp, settle, waitForRoute } from '@/__tests__/helpers'

type Wrapper = Awaited<ReturnType<typeof mountApp>>['wrapper']

/** Добавляет в мок-базу работы автора до общего числа `total` его работ. */
function seedWorks(total: number, user: { id: number; username: string } = { id: 2, username: 'designer' }): void {
  const template = db.generations[0]!
  const have = db.generations.filter((g) => g.user_id === user.id).length
  for (let i = have; i < total; i++) {
    const id = db.nextGenerationId++
    const work: Generation = {
      ...template,
      id,
      user_id: user.id,
      username: user.username,
      parent_id: null,
      batch_id: `fixture-${id}`,
      prompt: `Работа для пагинации ${id}`,
      inputs: [],
      shared: true,
      created_at: new Date(Date.parse('2026-10-28T00:00:00Z') + id * 60_000).toISOString(),
    }
    db.generations.push(work)
  }
}

async function login(who: keyof typeof MOCK_ACCOUNTS = 'designer'): Promise<void> {
  await auth.login(MOCK_ACCOUNTS[who].username, MOCK_ACCOUNTS[who].password)
}

const cardIds = (w: Wrapper) => w.findAll('[data-testid="work-card"]').map((c) => Number(c.attributes('data-work-id')))
const dialog = () => document.querySelector<HTMLElement>('[data-testid="work-dialog"]')
const inDialog = (testid: string) => document.querySelector<HTMLElement>(`[data-testid="work-dialog"] [data-testid="${testid}"]`)

/** Запросы к API за время теста: метод и путь с параметрами. */
function recordRequests(): string[] {
  const log: string[] = []
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url)
    log.push(`${request.method} ${url.pathname}${url.search}`)
  })
  return log
}

afterEach(() => {
  server.events.removeAllListeners()
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('галерея: подгрузка', () => {
  it('120 работ приходят страницами по 50 без дублей (показатель 1)', async () => {
    seedWorks(120)
    await login()
    const requests = recordRequests()
    const { wrapper } = await mountApp('/gallery')

    expect(cardIds(wrapper)).toHaveLength(50)
    await wrapper.find('[data-testid="load-more"]').trigger('click')
    await settle()
    expect(cardIds(wrapper)).toHaveLength(100)
    await wrapper.find('[data-testid="load-more"]').trigger('click')
    await settle()

    const ids = cardIds(wrapper)
    expect(ids).toHaveLength(120)
    expect(new Set(ids).size).toBe(120)
    // от новых к старым
    expect(ids).toEqual([...ids].sort((a, b) => b - a))
    expect(wrapper.find('[data-testid="load-more"]').exists()).toBe(false)

    const pages = requests.filter((r) => r.startsWith('GET /api/generations?'))
    expect(pages).toHaveLength(3)
    for (const p of pages) expect(p).toContain('limit=50')
    expect(pages[0]).not.toContain('cursor=')
    expect(pages[1]).toContain('cursor=')
  })

  it('следующая страница грузится, когда низ сетки попадает в экран', async () => {
    let fire: ((entries: Partial<IntersectionObserverEntry>[]) => void) | null = null
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(cb: (entries: Partial<IntersectionObserverEntry>[]) => void) {
          fire = cb
        }
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    )
    seedWorks(120)
    await login()
    const { wrapper } = await mountApp('/gallery')
    expect(cardIds(wrapper)).toHaveLength(50)
    fire!([{ isIntersecting: true }])
    await settle()
    expect(cardIds(wrapper)).toHaveLength(100)
    // повторный сигнал во время пустой ленты не дублирует работы
    fire!([{ isIntersecting: true }])
    fire!([{ isIntersecting: true }])
    await settle()
    expect(new Set(cardIds(wrapper)).size).toBe(cardIds(wrapper).length)
    expect(cardIds(wrapper)).toHaveLength(120)
  })

  it('у превью есть loading="lazy" (показатель 7)', async () => {
    await login()
    const { wrapper } = await mountApp('/gallery?tab=shared')
    const imgs = wrapper.findAll('[data-testid="work-card"] img')
    expect(imgs.length).toBe(3)
    for (const img of imgs) {
      expect(img.attributes('loading')).toBe('lazy')
      expect(img.attributes('src')).toContain('kind=thumb')
    }
  })
})

describe('галерея: вкладки и фильтр', () => {
  it('«Мои» — только свои, «Общая» — все общие с автором', async () => {
    await login()
    const { wrapper, router } = await mountApp('/gallery')
    expect(cardIds(wrapper)).toEqual([2, 1])
    await wrapper.find('[data-testid="tab-shared"]').trigger('click')
    await settle()
    expect(router.currentRoute.value.query.tab).toBe('shared')
    expect(cardIds(wrapper)).toEqual([3, 2, 1])
    expect(wrapper.find('[data-testid="work-card"]').text()).toContain('admin')
  })

  it('фильтр по автору в «Общей» отправляет author_id', async () => {
    await login()
    const requests = recordRequests()
    const { wrapper } = await mountApp('/gallery?tab=shared')
    const select = wrapper.find('[data-testid="author-filter"]')
    expect(select.findAll('option').map((o) => o.text())).toEqual(['Все', 'admin', 'designer'])
    await select.setValue('1')
    await settle()
    expect(cardIds(wrapper)).toEqual([3])
    expect(requests.at(-1)).toContain('author_id=1')
  })
})

describe('галерея: диалог работы', () => {
  it('показывает результат, референсы, промпт и параметры', async () => {
    await login()
    await mountApp('/gallery?id=2')
    const d = dialog()!
    expect(d).not.toBeNull()
    expect(d.getAttribute('role')).toBe('dialog')
    expect(d.querySelector('img')?.getAttribute('src')).toContain('/api/generations/2/image?kind=result')
    expect(inDialog('work-prompt')!.textContent).toContain('рюши')
    expect(inDialog('work-author')!.textContent).toBe('designer')
    expect(inDialog('work-cost')!.textContent).toBe('0,14\u00a0USD')
    expect(d.textContent).toContain('GPT Image 2.5 Sunburst')
    expect(d.textContent).toContain('1024x1024')
    expect(inDialog('work-inputs')!.querySelectorAll('img')).toHaveLength(1)
    const download = inDialog('download-work') as HTMLAnchorElement
    expect(download.getAttribute('href')).toContain('download=true')
    expect(download.getAttribute('download')).toBe('design-2.jpg')
  })

  it('«Править дальше» и «Повторить» ведут на экран генерации с ?ref и ?repeat', async () => {
    await login()
    // Экран генерации сам убирает ?ref/?repeat из адреса после чтения,
    // поэтому проверяем адрес перехода, а не адрес после него.
    const first = await mountApp('/gallery?id=2')
    const firstTargets: string[] = []
    first.router.afterEach((to) => void firstTargets.push(to.fullPath))
    inDialog('edit-further')!.click()
    await waitForRoute(first.router, 'generate')
    expect(first.router.currentRoute.value.name).toBe('generate')
    expect(firstTargets).toContain('/generate?ref=2')
    first.wrapper.unmount()

    const second = await mountApp('/gallery?tab=shared&id=3')
    const secondTargets: string[] = []
    second.router.afterEach((to) => void secondTargets.push(to.fullPath))
    inDialog('repeat-work')!.click()
    await waitForRoute(second.router, 'generate')
    expect(secondTargets).toContain('/generate?repeat=3')
  })

  it('Esc закрывает диалог, стрелки листают', async () => {
    await login()
    const { router } = await mountApp('/gallery?tab=shared&id=3')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await settle()
    expect(router.currentRoute.value.query.id).toBe('2')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    await settle()
    expect(router.currentRoute.value.query.id).toBe('3')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await settle()
    expect(dialog()).toBeNull()
    expect(router.currentRoute.value.query.id).toBeUndefined()
    expect(document.activeElement?.closest('[data-work-id]')?.getAttribute('data-work-id')).toBe('3')
  })

  it('«Видна всем» отправляет PATCH, после обновления работы нет в «Общей» (показатель 2)', async () => {
    await login()
    const requests = recordRequests()
    const { wrapper } = await mountApp('/gallery?tab=shared&id=2')
    const toggle = inDialog('shared-toggle') as HTMLInputElement
    expect(toggle.checked).toBe(true)
    toggle.checked = false
    toggle.dispatchEvent(new Event('change'))
    await settle()
    expect(requests).toContain('PATCH /api/generations/2')
    expect(db.generations.find((g) => g.id === 2)!.shared).toBe(false)
    wrapper.unmount()

    // другой пользователь (не автор и не админ) после обновления её не видит
    seedWorks(1, { id: 4, username: 'other' })
    db.users.push({ ...db.users[1]!, id: 4, username: 'other', password: 'other12345' })
    await auth.logout()
    await auth.login('other', 'other12345')
    const reloaded = await mountApp('/gallery?tab=shared')
    expect(cardIds(reloaded.wrapper)).not.toContain(2)
    expect(cardIds(reloaded.wrapper)).toContain(1)
  })

  it('автор после выключения видит пометку «приватная» в «Моих»', async () => {
    await login()
    db.generations.find((g) => g.id === 1)!.shared = false
    const { wrapper } = await mountApp('/gallery')
    const card = wrapper.find('[data-work-id="1"]')
    expect(card.find('[data-testid="private-badge"]').exists()).toBe(true)
  })

  it('на чужой работе нет «Удалить» и переключателя (показатель 4)', async () => {
    await login()
    await mountApp('/gallery?tab=shared&id=3')
    expect(dialog()).not.toBeNull()
    expect(inDialog('delete-work')).toBeNull()
    expect(inDialog('shared-toggle')).toBeNull()
    expect(inDialog('repeat-work')).not.toBeNull()
  })

  it('на своей работе и у админа на чужой — «Удалить» и переключатель есть', async () => {
    await login()
    const own = await mountApp('/gallery?id=2')
    expect(inDialog('delete-work')).not.toBeNull()
    expect(inDialog('shared-toggle')).not.toBeNull()
    own.wrapper.unmount()

    await auth.logout()
    await login('admin')
    await mountApp('/gallery?tab=shared&id=2')
    expect(inDialog('delete-work')).not.toBeNull()
    expect(inDialog('shared-toggle')).not.toBeNull()
  })

  it('удаление только после подтверждения, затем карточка исчезает', async () => {
    await login()
    const requests = recordRequests()
    const { wrapper } = await mountApp('/gallery?id=2')
    inDialog('delete-work')!.click()
    await settle()
    expect(requests.some((r) => r.startsWith('DELETE'))).toBe(false)
    inDialog('cancel-delete')!.click()
    await settle()
    expect(cardIds(wrapper)).toContain(2)

    inDialog('delete-work')!.click()
    await settle()
    inDialog('confirm-delete')!.click()
    await settle()
    expect(requests).toContain('DELETE /api/generations/2')
    expect(dialog()).toBeNull()
    expect(cardIds(wrapper)).toEqual([1])
  })
})

describe('галерея: пустые состояния', () => {
  it('«Пока нет работ» с кнопкой «Создать работу» (показатель 5)', async () => {
    db.generations = []
    await login()
    const { wrapper, router } = await mountApp('/gallery')
    const empty = wrapper.find('[data-testid="empty-state"]')
    expect(empty.text()).toContain('Пока нет работ')
    const create = empty.find('[data-testid="create-work"]')
    expect(create.text()).toBe('Создать работу')
    await create.trigger('click')
    await settle()
    expect(router.currentRoute.value.name).toBe('generate')
  })

  it('пока грузится первая страница, видны скелетоны', async () => {
    let open!: () => void
    const gate = new Promise<void>((r) => (open = r))
    // ответ списка задерживается до open(), потом его отдаёт обычный обработчик мока
    server.use(http.get('*/api/generations', async () => void (await gate)))
    await login()
    const { wrapper } = await mountApp('/gallery')
    expect(wrapper.find('[data-testid="skeletons"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(false)
    open()
    await settle()
    expect(wrapper.find('[data-testid="skeletons"]').exists()).toBe(false)
    expect(cardIds(wrapper)).toEqual([2, 1])
  })
})
