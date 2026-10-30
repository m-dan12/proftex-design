import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { vi } from 'vitest'
import App from '@/App.vue'
import { createAppRouter } from '@/router'

/** Монтирует всё приложение на маршруте `path` с памятью вместо адресной строки. */
export async function mountApp(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body })
  await settle()
  return { wrapper, router }
}

/** Ждёт ленивые компоненты маршрутов и ответы мок-API. */
export async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await flushPromises()
    await new Promise((r) => setTimeout(r, 0))
  }
}

export async function waitForRoute(router: ReturnType<typeof createAppRouter>, name: string) {
  await vi.waitFor(() => {
    if (router.currentRoute.value.name !== name) throw new Error(`маршрут ${String(router.currentRoute.value.name)}`)
  })
  await settle()
}
