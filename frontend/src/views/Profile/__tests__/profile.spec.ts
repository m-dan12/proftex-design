// Показатель 3 карточки T13: смена пароля в профиле; плюс имя и выход из аккаунта.
import { afterEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import type { VueWrapper } from '@vue/test-utils'
import { server } from '@/mocks/node'
import { db, MOCK_ACCOUNTS } from '@/mocks/db'
import { auth } from '@/stores/auth'
import { mountApp, settle, waitForRoute } from '@/__tests__/helpers'

async function openProfile(account: keyof typeof MOCK_ACCOUNTS = 'designer') {
  await auth.login(MOCK_ACCOUNTS[account].username, MOCK_ACCOUNTS[account].password)
  return mountApp('/profile')
}

const field = (w: VueWrapper, name: 'old' | 'new' | 'repeat') => w.find(`[data-testid="pw-${name}"]`)
const fieldError = (w: VueWrapper, name: 'old' | 'new' | 'repeat') => w.find(`[data-testid="pw-${name}-error"]`)

async function fill(w: VueWrapper, old: string, next: string, repeat = next) {
  await field(w, 'old').setValue(old)
  await field(w, 'new').setValue(next)
  await field(w, 'repeat').setValue(repeat)
}

async function submit(w: VueWrapper) {
  await w.find('[data-testid="pw-form"]').trigger('submit')
  await settle()
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('профиль', () => {
  it('показывает имя пользователя и роль', async () => {
    const { wrapper } = await openProfile('admin')
    expect(wrapper.find('[data-testid="profile-username"]').text()).toBe('admin')
    expect(wrapper.find('[data-testid="profile-role"]').text()).toBe('Администратор')
  })

  it('короткий новый пароль: ошибка после выхода из поля, запрос не уходит', async () => {
    let calls = 0
    server.use(
      http.post('*/api/me/password', () => {
        calls++
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { wrapper } = await openProfile()
    await field(wrapper, 'new').setValue('short')
    // пока пользователь в поле, ошибки нет
    expect(fieldError(wrapper, 'new').exists()).toBe(false)
    await field(wrapper, 'new').trigger('blur')
    expect(fieldError(wrapper, 'new').text()).toBe('Новый пароль — не короче 8 символов')
    expect(field(wrapper, 'new').attributes('aria-invalid')).toBe('true')

    await fill(wrapper, MOCK_ACCOUNTS.designer.password, 'short')
    await submit(wrapper)
    expect(calls).toBe(0)
    expect(wrapper.find('[data-testid="pw-success"]').exists()).toBe(false)

    // исправили — ошибка уходит
    await field(wrapper, 'new').setValue('long-enough-1')
    await field(wrapper, 'new').trigger('blur')
    expect(fieldError(wrapper, 'new').exists()).toBe(false)
  })

  it('повтор не совпадает: ошибка после выхода из поля', async () => {
    const { wrapper } = await openProfile()
    await field(wrapper, 'new').setValue('new-password-1')
    await field(wrapper, 'repeat').setValue('new-password-2')
    await field(wrapper, 'repeat').trigger('blur')
    expect(fieldError(wrapper, 'repeat').text()).toBe('Пароли не совпадают')
  })

  it('пустой старый пароль: ошибка при отправке', async () => {
    const { wrapper } = await openProfile()
    await fill(wrapper, '', 'new-password-1')
    await submit(wrapper)
    expect(fieldError(wrapper, 'old').text()).toBe('Введите текущий пароль')
  })

  it('неверный старый пароль показывает понятную ошибку', async () => {
    const { wrapper } = await openProfile()
    await fill(wrapper, 'wrong-old-password', 'new-password-1')
    await submit(wrapper)
    expect(wrapper.find('[data-testid="pw-error"]').text()).toBe('Старый пароль неверный')
    expect(wrapper.find('[data-testid="pw-success"]').exists()).toBe(false)
    expect(db.users.find((u) => u.username === 'designer')?.password).toBe(MOCK_ACCOUNTS.designer.password)
  })

  it('422 без текста (ошибка валидации FastAPI) тоже объясняется по-русски', async () => {
    server.use(
      http.post('*/api/me/password', () =>
        HttpResponse.json({ detail: [{ loc: ['body', 'new_password'], msg: 'too short' }] }, { status: 422 }),
      ),
    )
    const { wrapper } = await openProfile()
    await fill(wrapper, MOCK_ACCOUNTS.designer.password, 'new-password-1')
    await submit(wrapper)
    expect(wrapper.find('[data-testid="pw-error"]').text()).toBe(
      'Не удалось сменить пароль: проверьте текущий пароль и длину нового (не короче 8 символов)',
    )
  })

  it('успех показывает сообщение, очищает поля, новый пароль работает', async () => {
    const { wrapper } = await openProfile()
    await fill(wrapper, MOCK_ACCOUNTS.designer.password, 'new-password-1')
    await submit(wrapper)
    expect(wrapper.find('[data-testid="pw-success"]').text()).toBe('Пароль изменён')
    expect(wrapper.find('[data-testid="pw-error"]').exists()).toBe(false)
    for (const name of ['old', 'new', 'repeat'] as const) {
      expect((field(wrapper, name).element as HTMLInputElement).value).toBe('')
    }
    expect(db.users.find((u) => u.username === 'designer')?.password).toBe('new-password-1')
  })

  it('«Выйти из аккаунта» ведёт на /login', async () => {
    const { wrapper, router } = await openProfile()
    await wrapper.find('[data-testid="profile-logout"]').trigger('click')
    await waitForRoute(router, 'login')
    expect(auth.state.user).toBeNull()
  })
})
