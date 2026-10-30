# Отчёт T15 · интеграция и e2e на заглушке

## Что сделано

- **Хвосты волны 2**
  - eslint во фронтенде (`frontend/eslint.config.js`, скрипт `npm run lint`), входит в `make check`;
  - один формат сумм «12,34 USD» везде (`formatMoney` в `frontend/src/utils/format.ts`, `formatUsd` удалён);
  - администратор при старте создавался уже в T08 (`ensure_admin` в lifespan `routers/auth.py`, тест `test_auth.py`), доработка не потребовалась;
  - единый обработчик 422 в `backend/app/main.py` вместо `ApiRoute` на двух роутерах: теперь `detail` — строка на всех маршрутах (тест `test_validation_errors.py`).
- **Сборка вместе:** бэкенд отдаёт `frontend/dist` с запасным `index.html` для адресов фронтенда (`FRONTEND_DIST`, тест `test_frontend_dist.py`).
- **Контракт:** тест `test_operation_is_mounted` теперь ещё и требует «не 501».
- **e2e (Playwright, `e2e/`, 14 сценариев):** S-03, S-04, S-05, S-06, S-08, S-10, S-11, S-15. Три прогона подряд без падений.
- **`scripts/load_check.py`** (S-07): 6 запусков, пик `running` = 4, все `done`, `/api/health` ≤ 5 мс.
- **`scripts/security_check.sh`** (S-14): ключ не в git, Dockerfile, ответах и логах; `.exe` под видом `.png` → 422; файл больше 20 МБ → 413; «бомба» 20000×20000 → 422 при памяти ≤ 1 ГБ; чужая приватная картинка и `../` → 404.
- **`make check`** дополнен целями `check-e2e` и `check-scripts`.

## Правки в чужих файлах

| Файл | Владелец | Правка | Причина |
|---|---|---|---|
| `backend/app/db.py` | T02 | `check_same_thread=False` в `connect()` | зависимость `get_db` — генератор: FastAPI открывает и закрывает её в разных потоках пула, закрытие падало с `sqlite3.ProgrammingError` (нашли e2e); тест `test_connection_can_close_in_another_thread` |
| `backend/app/main.py` | T01 | обработчик 422, отдача `frontend/dist` | см. выше |
| `backend/app/deps.py`, `routers/auth.py`, `routers/users.py` | T08 | убран `ApiRoute` | заменён общим обработчиком |
| `backend/tests/test_contract_routes.py` | T01 | `501` в недопустимых кодах | критерий 4 |
| `backend/tests/test_core.py` | T02 | тест про потоки | см. `db.py` |
| `frontend/index.html` | T03 | иконка сайта data-URI | `/favicon.ico` давал 404 и ошибку в консоли (S-15) |
| `frontend/src/utils/format.ts`, `views/Spending/money.ts` | T03, T13 | `formatMoney` перенесён в общий модуль | единый формат сумм |
| `views/Gallery/WorkDialog.vue`, `Generate/GenerateView.vue`, `Generate/ResultBatch.vue`, `Admin/SpendingTab.vue`, `Profile/ProfileView.vue`, `Spending/*.vue` и их тесты | T11–T14 | перешли на `formatMoney` | единый формат сумм |
| `frontend/package.json`, `package-lock.json` | T03 | зависимости eslint, скрипт `lint` | eslint |
| `.gitignore` | T01 | `e2e/.data/`, `e2e/node_modules` | артефакты e2e |

## Что не проверено локально

- `Secure` у cookie: e2e идёт по http с `COOKIE_SECURE=0`, флаг проверяют тесты pytest; на VDS — в S-03 из `curl -i`.
- «Ключ не в образе»: образ не собирался (нет Docker), проверен `deploy/Dockerfile` статически.
