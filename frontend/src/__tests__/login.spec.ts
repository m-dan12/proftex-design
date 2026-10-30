import { describe, expect, it } from 'vitest'
import { MOCK_ACCOUNTS } from '@/mocks/db'
import { mountApp, settle, waitForRoute } from './helpers'

async function fillAndSubmit(wrapper: Awaited<ReturnType<typeof mountApp>>['wrapper'], u: string, p: string) {
  await wrapper.find('#login-username').setValue(u)
  await wrapper.find('#login-password').setValue(p)
  await wrapper.find('form').trigger('submit')
  await settle()
}

describe('экран входа', () => {
  it('успешный вход открывает layout с именем пользователя', async () => {
    const { wrapper, router } = await mountApp('/login')
    await fillAndSubmit(wrapper, MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    await waitForRoute(router, 'generate')
    expect(wrapper.find('[data-testid="username"]').text()).toBe('designer')
    expect(wrapper.find('[data-testid="login-error"]').exists()).toBe(false)
  })

  it('после входа возвращает на страницу из redirect', async () => {
    const { wrapper, router } = await mountApp('/spending')
    await fillAndSubmit(wrapper, MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    await waitForRoute(router, 'spending')
  })

  it('не уводит на внешний адрес из redirect', async () => {
    const { wrapper, router } = await mountApp('/login?redirect=//evil.example')
    await fillAndSubmit(wrapper, MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    await waitForRoute(router, 'generate')
  })

  it('неверный пароль (401) показывает ошибку и остаётся на /login', async () => {
    const { wrapper, router } = await mountApp('/login')
    await fillAndSubmit(wrapper, 'designer', 'wrong-password')
    expect(router.currentRoute.value.name).toBe('login')
    expect(wrapper.find('[data-testid="login-error"]').text()).toBe('Неверный логин или пароль')
    expect((wrapper.find('#login-password').element as HTMLInputElement).value).toBe('')
  })

  it('заблокированный (403) видит текст сервера', async () => {
    const { wrapper } = await mountApp('/login')
    await fillAndSubmit(wrapper, MOCK_ACCOUNTS.blocked.username, MOCK_ACCOUNTS.blocked.password)
    expect(wrapper.find('[data-testid="login-error"]').text()).toBe('Пользователь заблокирован')
  })

  it('6-я попытка за минуту (429) показывает текст сервера', async () => {
    const { wrapper } = await mountApp('/login')
    for (let i = 0; i < 5; i++) await fillAndSubmit(wrapper, 'designer', `bad-${i}`)
    await fillAndSubmit(wrapper, 'designer', MOCK_ACCOUNTS.designer.password)
    expect(wrapper.find('[data-testid="login-error"]').text()).toContain('Слишком много попыток')
  })

  it('пустые поля не отправляются', async () => {
    const { wrapper } = await mountApp('/login')
    await fillAndSubmit(wrapper, '', '')
    expect(wrapper.find('[data-testid="login-error"]').text()).toBe('Введите логин и пароль')
  })

  it('выход возвращает на /login', async () => {
    const { wrapper, router } = await mountApp('/login')
    await fillAndSubmit(wrapper, MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    await waitForRoute(router, 'generate')
    const logout = wrapper.findAll('button').find((b) => b.text() === 'Выйти')!
    await logout.trigger('click')
    await waitForRoute(router, 'login')
  })
})
