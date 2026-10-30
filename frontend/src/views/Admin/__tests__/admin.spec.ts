// Показатели 1–5 карточки T14 (админка) на мок-API.
import { describe, expect, it, vi } from 'vitest'
import type { VueWrapper } from '@vue/test-utils'
import { auth } from '@/stores/auth'
import { db, MOCK_ACCOUNTS } from '@/mocks/db'
import { mountApp, settle } from '@/__tests__/helpers'
import { validatePassword, validateUsername } from '../validate'

async function openAdmin(path = '/admin') {
  await auth.login(MOCK_ACCOUNTS.admin.username, MOCK_ACCOUNTS.admin.password)
  return mountApp(path)
}

const row = (w: VueWrapper, username: string) => {
  const r = w.findAll('[data-testid="user-row"]').find((x) => x.attributes('data-username') === username)
  if (!r) throw new Error(`нет строки ${username}`)
  return r
}

const mockUser = (username: string) => {
  const u = db.users.find((x) => x.username === username)
  if (!u) throw new Error(`нет пользователя ${username}`)
  return u
}

async function fillCreate(w: VueWrapper, username: string, password: string) {
  await w.find('#new-username').setValue(username)
  await w.find('#new-password').setValue(password)
  await w.find('[data-testid="create-form"]').trigger('submit')
  await settle()
}

describe('T14 · 1: создание пользователя', () => {
  it('правила логина и пароля', () => {
    expect(validateUsername('ab')).not.toBe('')
    expect(validateUsername('иван')).not.toBe('')
    expect(validateUsername('a b')).not.toBe('')
    expect(validateUsername('a'.repeat(33))).not.toBe('')
    expect(validateUsername('abc')).toBe('')
    expect(validateUsername('ivan.petrov_2-x')).toBe('')
    expect(validatePassword('1234567')).not.toBe('')
    expect(validatePassword('12345678')).toBe('')
  })

  it('неверный логин и короткий пароль показывают ошибки и не отправляют запрос', async () => {
    const { wrapper } = await openAdmin()
    const before = db.users.length
    await fillCreate(wrapper, 'ab', 'short')
    expect(wrapper.find('[data-testid="username-error"]').text()).toMatch(/от 3/)
    expect(wrapper.find('[data-testid="password-error"]').text()).toMatch(/8/)
    expect(db.users.length).toBe(before)
  })

  it('новый пользователь появляется в таблице, форма очищается', async () => {
    const { wrapper } = await openAdmin()
    await fillCreate(wrapper, 'new.user_1', 'password123')
    expect(row(wrapper, 'new.user_1').exists()).toBe(true)
    expect(mockUser('new.user_1').is_admin).toBe(false)
    expect((wrapper.find('#new-username').element as HTMLInputElement).value).toBe('')
    expect((wrapper.find('#new-password').element as HTMLInputElement).value).toBe('')
  })

  it('повторный логин даёт понятную ошибку', async () => {
    const { wrapper } = await openAdmin()
    await fillCreate(wrapper, 'designer', 'password123')
    expect(wrapper.find('[data-testid="create-error"]').text()).toContain('Такой логин уже есть')
  })
})

describe('T14 · 2: сброс пароля', () => {
  it('новый пароль показан один раз с кнопкой «Скопировать» и исчезает после закрытия', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const { wrapper } = await openAdmin()
    await row(wrapper, 'designer').find('[data-testid="reset-password"]').trigger('click')
    await settle()
    // сначала подтверждение: старый пароль перестанет работать
    await wrapper.find('[data-testid="dialog-confirm"]').trigger('click')
    await settle()
    const password = mockUser('designer').password
    expect(password).toHaveLength(12)
    expect(wrapper.find('[data-testid="new-password"]').text()).toBe(password)

    const copy = wrapper.find('[data-testid="copy-password"]')
    expect(copy.text()).toContain('Скопировать')
    await copy.trigger('click')
    await settle()
    expect(writeText).toHaveBeenCalledWith(password)
    expect(copy.text()).toContain('Скопировано')

    await wrapper.find('[data-testid="dialog-close"]').trigger('click')
    await settle()
    expect(wrapper.find('[data-testid="new-password"]').exists()).toBe(false)
    expect(document.body.textContent).not.toContain(password)
  })
})

describe('T14 · 3: блокировка', () => {
  it('требует подтверждения; отмена ничего не меняет', async () => {
    const { wrapper } = await openAdmin()
    await row(wrapper, 'designer').find('[data-testid="toggle-active"]').trigger('click')
    await settle()
    expect(wrapper.find('[role="dialog"]').text()).toContain('designer')
    expect(mockUser('designer').is_active).toBe(true)
    await wrapper.find('[data-testid="dialog-cancel"]').trigger('click')
    await settle()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(mockUser('designer').is_active).toBe(true)
  })

  it('после подтверждения помечен «Заблокирован»; разблокировка снимает пометку', async () => {
    const { wrapper } = await openAdmin()
    expect(row(wrapper, 'designer').find('[data-testid="blocked-badge"]').exists()).toBe(false)
    await row(wrapper, 'designer').find('[data-testid="toggle-active"]').trigger('click')
    await settle()
    await wrapper.find('[data-testid="dialog-confirm"]').trigger('click')
    await settle()
    expect(mockUser('designer').is_active).toBe(false)
    expect(row(wrapper, 'designer').find('[data-testid="blocked-badge"]').text()).toBe('Заблокирован')
    expect(row(wrapper, 'designer').classes()).toContain('blocked')

    await row(wrapper, 'designer').find('[data-testid="toggle-active"]').trigger('click')
    await settle()
    expect(mockUser('designer').is_active).toBe(true)
    expect(row(wrapper, 'designer').find('[data-testid="blocked-badge"]').exists()).toBe(false)
  })

  it('заблокированный в моке помечен сразу; себя заблокировать нельзя', async () => {
    const { wrapper } = await openAdmin()
    expect(row(wrapper, 'blocked').find('[data-testid="blocked-badge"]').exists()).toBe(true)
    expect(row(wrapper, 'admin').find('[data-testid="toggle-active"]').attributes('disabled')).toBeDefined()
  })
})

describe('T14 · 4: расходы', () => {
  async function openSpending(group: 'user' | 'model' | 'day') {
    const res = await openAdmin('/admin?tab=spending')
    const w = res.wrapper
    await w.find('[data-testid="period-custom"]').trigger('click')
    await w.find('#spend-from').setValue('2026-10-01')
    await w.find('#spend-to').setValue('2026-10-31')
    await w.find('#spend-group').setValue(group)
    await settle()
    return res
  }

  it.each(['user', 'model', 'day'] as const)('сумма строк равна итогу (группировка %s)', async (group) => {
    const { wrapper } = await openSpending(group)
    const rows = wrapper.findAll('[data-testid="spend-row"]')
    expect(rows.length).toBeGreaterThan(0)
    const sum = rows.reduce((s, r) => s + Number(r.attributes('data-micro')), 0)
    const expected = db.generations.reduce((s, g) => s + g.cost_micro_usd, 0)
    const total = wrapper.find('[data-testid="spend-total"]')
    expect(sum).toBe(expected)
    expect(Number(total.attributes('data-micro'))).toBe(expected)
    expect(total.text()).toContain('0,43\u00a0USD')
  })

  it('ссылка на CSV содержит те же период и группировку', async () => {
    const { wrapper } = await openSpending('model')
    const href = wrapper.find('[data-testid="csv-link"]').attributes('href')!
    const url = new URL(href, 'http://x')
    expect(url.pathname).toBe('/api/admin/spending.csv')
    expect(Object.fromEntries(url.searchParams)).toEqual({ from: '2026-10-01', to: '2026-10-31', group: 'model' })
  })

  it('пресет «7 дней» задаёт период из 7 суток в запросе и ссылке', async () => {
    const { wrapper } = await openAdmin('/admin?tab=spending')
    await wrapper.find('[data-testid="period-7"]').trigger('click')
    await settle()
    const url = new URL(wrapper.find('[data-testid="csv-link"]').attributes('href')!, 'http://x')
    const days = (Date.parse(url.searchParams.get('to')!) - Date.parse(url.searchParams.get('from')!)) / 86_400_000
    expect(days).toBe(6)
    expect(url.searchParams.get('group')).toBe('user')
  })

  it('пустой период показывает пустое состояние', async () => {
    const { wrapper } = await openAdmin('/admin?tab=spending')
    await wrapper.find('[data-testid="period-custom"]').trigger('click')
    await wrapper.find('#spend-from').setValue('2020-01-01')
    await wrapper.find('#spend-to').setValue('2020-01-31')
    await settle()
    expect(wrapper.findAll('[data-testid="spend-row"]')).toHaveLength(0)
    expect(wrapper.find('[data-testid="spend-empty"]').exists()).toBe(true)
  })
})

describe('T14 · 5: доступ и вкладки', () => {
  it('не-админа /admin редиректит на /generate', async () => {
    await auth.login(MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    const { router, wrapper } = await mountApp('/admin')
    expect(router.currentRoute.value.name).toBe('generate')
    expect(wrapper.find('[data-testid="admin-tabs"]').exists()).toBe(false)
  })

  it('неавторизованного /admin ведёт на вход', async () => {
    const { router } = await mountApp('/admin?tab=spending')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/admin?tab=spending')
  })

  it('вкладки переключаются и запоминаются в адресе', async () => {
    const { wrapper, router } = await openAdmin()
    expect(wrapper.find('[data-testid="users-table"]').exists()).toBe(true)
    await wrapper.find('[data-testid="tab-spending"]').trigger('click')
    await settle()
    expect(router.currentRoute.value.query.tab).toBe('spending')
    expect(wrapper.find('[data-testid="spend-total"]').exists()).toBe(true)
  })
})
