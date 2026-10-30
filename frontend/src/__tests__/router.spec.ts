import { describe, expect, it } from 'vitest'
import { auth } from '@/stores/auth'
import { MOCK_ACCOUNTS } from '@/mocks/db'
import { mountApp } from './helpers'

const navLabels = (w: Awaited<ReturnType<typeof mountApp>>['wrapper']) =>
  w.findAll('[data-testid="nav-link"]').map((a) => a.text())

describe('охранники маршрутов', () => {
  it('неавторизованный на / попадает на /login', async () => {
    const { router, wrapper } = await mountApp('/')
    expect(router.currentRoute.value.name).toBe('login')
    expect(wrapper.find('form').exists()).toBe(true)
  })

  it('неавторизованный на /gallery попадает на /login с redirect', async () => {
    const { router } = await mountApp('/gallery')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/gallery')
  })

  it('после входа / открывает layout с навигацией', async () => {
    await auth.login(MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    const { router, wrapper } = await mountApp('/')
    expect(router.currentRoute.value.name).toBe('generate')
    expect(wrapper.find('header nav').exists()).toBe(true)
    expect(navLabels(wrapper)).toEqual(['Создать', 'Галерея', 'Расходы', 'Профиль'])
  })

  it('все экраны зарегистрированы и открываются', async () => {
    await auth.login(MOCK_ACCOUNTS.admin.username, MOCK_ACCOUNTS.admin.password)
    for (const name of ['generate', 'gallery', 'spending', 'profile', 'admin']) {
      const { router, wrapper } = await mountApp(`/${name}`)
      expect(router.currentRoute.value.name).toBe(name)
      expect(wrapper.find('main h1').exists()).toBe(true)
      wrapper.unmount()
    }
  })

  it('не-админ не видит «Админ» и по прямой ссылке уходит на /generate', async () => {
    await auth.login(MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    const { router, wrapper } = await mountApp('/admin')
    expect(router.currentRoute.value.name).toBe('generate')
    expect(navLabels(wrapper)).not.toContain('Админ')
  })

  it('админ видит «Админ» и открывает /admin', async () => {
    await auth.login(MOCK_ACCOUNTS.admin.username, MOCK_ACCOUNTS.admin.password)
    const { router, wrapper } = await mountApp('/admin')
    expect(router.currentRoute.value.name).toBe('admin')
    expect(navLabels(wrapper)).toContain('Админ')
  })

  it('вошедший на /login уходит в layout', async () => {
    await auth.login(MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    const { router } = await mountApp('/login')
    expect(router.currentRoute.value.name).toBe('generate')
  })

  it('неизвестный путь ведёт на главную', async () => {
    await auth.login(MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
    const { router } = await mountApp('/nope/42')
    expect(router.currentRoute.value.name).toBe('generate')
  })
})
