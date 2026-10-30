import { createApp } from 'vue'
import App from './App.vue'
import { createAppRouter } from './router'
import { setUnauthorizedHandler } from './api/client'
import { auth } from './stores/auth'
import { initTheme } from './theme'
import './styles/theme.css'

async function start(): Promise<void> {
  if (import.meta.env.VITE_MOCK === '1') {
    const { worker } = await import('./mocks/browser')
    await worker.start({ onUnhandledRequest: 'bypass', quiet: true })
  }
  initTheme()

  const router = createAppRouter()
  setUnauthorizedHandler(() => {
    auth.forget()
    const current = router.currentRoute.value
    if (!current.meta.public) {
      void router.replace({ name: 'login', query: { redirect: current.fullPath } })
    }
  })

  createApp(App).use(router).mount('#app')
}

void start()
