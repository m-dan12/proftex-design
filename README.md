# design.proftex.tech

Веб-сервис, через который дизайнеры генерируют и правят изображения моделями OpenAI; ключ API остаётся на сервере, администратор видит расходы.

- ТЗ: [`docs/TZ.md`](docs/TZ.md)
- Контракт API: [`contracts/openapi.yaml`](contracts/openapi.yaml) (заморожен после T01)
- Кто чем владеет: [`docs/OWNERSHIP.md`](docs/OWNERSHIP.md)

## Локально

```bash
make install   # зависимости бэкенда
(cd frontend && npm ci)
(cd e2e && npm ci && npx playwright install chromium)
make dev       # бэкенд на http://localhost:8000 (frontend/dist отдаётся, если собран: make build)
make check     # всё сразу, см. ниже
```

Сервис запускается только одним процессом Uvicorn (`--workers 1`). Без `OPENAI_API_KEY` работает режим заглушки. При пустой базе и заданном `ADMIN_PASSWORD` администратор создаётся при старте; иначе — `python -m app.manage create-admin`.

Бэкенд отдаёт собранный фронтенд из `frontend/dist` (путь можно задать переменной `FRONTEND_DIST`); неизвестные адреса вне `/api` получают `index.html`.

## Проверки: `make check`

| Цель | Что проверяет |
|---|---|
| `check-backend` | спецификация OpenAPI, `ruff`, `pytest` (контракт: все 19 операций смонтированы и не отвечают 501) |
| `check-frontend` | `vue-tsc`, `eslint`, `vitest` |
| `check-e2e` | собирает фронтенд и гоняет Playwright на заглушке: S-03…S-06, S-08, S-10, S-11, S-15 (`e2e/`) |
| `check-scripts` | `scripts/load_check.py` (S-07) и `scripts/security_check.sh` (S-14); сами поднимают временный сервис |

Если Chromium стоит не там, где ждёт Playwright, задайте `PW_CHROMIUM_PATH`. Скрипты проверки принимают `BASE_URL`, чтобы проверить уже запущенный сервис.

Деплой — в [`deploy/README.md`](deploy/README.md). Отчёт T15 с правками в чужих файлах — [`docs/T15-report.md`](docs/T15-report.md).
