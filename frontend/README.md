# Фронтенд design.proftex.tech

Vite + Vue 3 + TypeScript + Vue Router. Владелец каркаса — T03; папки экранов
`src/views/{Generate,Gallery,Spending,Profile,Admin}/` принадлежат T11–T14 (см. `docs/OWNERSHIP.md`).

## Запуск

```bash
npm ci
npm run dev:mock   # без бэкенда: все 19 операций API отвечает MSW (VITE_MOCK=1)
npm run dev        # с бэкендом: /api проксируется на http://127.0.0.1:8000 (make dev)
npm run build      # vue-tsc + сборка в dist/, её отдаёт FastAPI
```

Учётные записи мок-API: `admin` / `admin12345` (администратор), `designer` / `designer123`,
`blocked` / `blocked123` (заблокирован, вход даёт 403). Сессия мока живёт в `sessionStorage` вкладки.
Генерации в моке: `pending` → `running` через 1 с → `done` через 3 с; картинки — SVG-заглушки.

## Проверки

```bash
npx vue-tsc --noEmit   # типы
npx vitest run         # тесты (MSW в Node), входит в make check
npm run check:width    # Playwright: ширина 360 px без горизонтальной прокрутки и без ошибок в консоли
```

## Как устроено

| Путь | Что там |
| --- | --- |
| `src/api/types.ts` | типы из `contracts/openapi.yaml`, генерирует `npm run gen:api`; руками не править. Тест `types-sync.spec.ts` падает, если файл отстал от контракта |
| `src/api/client.ts` | `api` (openapi-fetch, пути и тела проверяются по контракту), `unwrap()` → данные или `ApiError(status, detail)`, `createGeneration(formData)`, `imageUrl(id, kind, {idx, download})`, псевдонимы типов `User`, `Generation`, … |
| `src/stores/auth.ts` | `auth.state.user`, `auth.isAdmin`, `login`, `logout`; любой 401 (кроме входа) выкидывает на `/login?redirect=…` |
| `src/router/index.ts` | все маршруты; `meta.admin` — только администратору, `meta.public` — без входа |
| `src/mocks/` | MSW: `handlers.ts` (по операции на каждый `operationId`), `db.ts` (данные), `browser.ts`, `node.ts` |
| `src/styles/theme.css` | CSS-переменные светлой и тёмной темы и общие классы: `.page`, `.card`, `.field`, `.input`, `.select`, `.textarea`, `.btn`, `.btn-primary`, `.btn-danger`, `.btn-ghost`, `.error`, `.muted` |
| `src/theme.ts` | выбор темы: как в системе → светлая → тёмная, хранится в `localStorage` |
| `src/utils/format.ts` | `formatUsd(micro)`, `formatDateTime(iso)`, `isoDate(date)` |

### Для экранов волны 2 (T11–T14)

Маршрут уже зарегистрирован и ведёт на `src/views/<Экран>/<Экран>View.vue` — замените содержимое
этого файла и добавляйте рядом свои компоненты. Корень экрана — `<section class="page">`, цвета только
через переменные из `theme.css`, чтобы работали обе темы. Параметры адреса, о которых договорились
маршруты: `/generate?ref=ID` и `/generate?repeat=ID`; `/gallery?tab=mine|shared&id=ID`.

```ts
import { api, unwrap, createGeneration, imageUrl, type Generation } from '@/api/client'

const models = await unwrap(api.GET('/api/models'))
const page = await unwrap(api.GET('/api/generations', { params: { query: { scope: 'mine' } } }))
```
