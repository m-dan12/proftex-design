# design.proftex.tech

Веб-сервис, через который дизайнеры генерируют и правят изображения моделями OpenAI; ключ API остаётся на сервере, администратор видит расходы.

- ТЗ: [`docs/TZ.md`](docs/TZ.md)
- Контракт API: [`contracts/openapi.yaml`](contracts/openapi.yaml) (заморожен после T01)
- Кто чем владеет: [`docs/OWNERSHIP.md`](docs/OWNERSHIP.md)

## Локально

```bash
make install   # зависимости бэкенда
make dev       # http://localhost:8000/api/health
make check     # спецификация, ruff, pytest (+ фронтенд, когда появится)
```

Сервис запускается только одним процессом Uvicorn (`--workers 1`). Без `OPENAI_API_KEY` работает режим заглушки.

Полный README с деплоем пишут T07 и T15.
