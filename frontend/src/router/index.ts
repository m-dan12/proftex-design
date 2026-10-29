// Маршруты всех экранов. Экраны волны 2 (T11–T14) лежат в src/views/<Экран>/<Экран>View.vue:
// их владельцы меняют содержимое своих папок, но не этот файл.
import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type Router,
  type RouterHistory,
} from 'vue-router'
import { auth } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    /** Доступен без входа (только экран входа). */
    public?: boolean
    /** Только администратору. */
    admin?: boolean
    /** Заголовок вкладки браузера. */
    title?: string
  }
}

export const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login/LoginView.vue'),
    meta: { public: true, title: 'Вход' },
  },
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    children: [
      { path: '', redirect: { name: 'generate' } },
      {
        // ?ref=ID — работа как референс, ?repeat=ID — повторить параметры работы
        path: 'generate',
        name: 'generate',
        component: () => import('@/views/Generate/GenerateView.vue'),
        meta: { title: 'Создать' },
      },
      {
        // ?tab=mine|shared, ?id=ID — открыть диалог работы
        path: 'gallery',
        name: 'gallery',
        component: () => import('@/views/Gallery/GalleryView.vue'),
        meta: { title: 'Галерея' },
      },
      {
        path: 'spending',
        name: 'spending',
        component: () => import('@/views/Spending/SpendingView.vue'),
        meta: { title: 'Расходы' },
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('@/views/Profile/ProfileView.vue'),
        meta: { title: 'Профиль' },
      },
      {
        path: 'admin',
        name: 'admin',
        component: () => import('@/views/Admin/AdminView.vue'),
        meta: { admin: true, title: 'Админ' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export function createAppRouter(history: RouterHistory = createWebHistory()): Router {
  const router = createRouter({ history, routes })

  router.beforeEach(async (to) => {
    await auth.ensureLoaded()
    const user = auth.state.user
    if (to.meta.public) {
      return user ? { name: 'generate' } : true
    }
    if (!user) {
      return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
    }
    if (to.matched.some((r) => r.meta.admin) && !user.is_admin) {
      return { name: 'generate' }
    }
    return true
  })

  router.afterEach((to) => {
    document.title = to.meta.title ? `${to.meta.title} · Дизайн-студия` : 'Дизайн-студия'
  })

  return router
}
