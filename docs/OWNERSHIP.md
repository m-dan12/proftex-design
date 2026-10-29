# Владельцы файлов

Каждый файл принадлежит ровно одной задаче. Агент правит только файлы своей задачи; остальное — заявкой оркестратору (раздел 10 ТЗ, `docs/TZ.md`).

Заглушки, которые T01 создаёт для других задач (роутеры, `deps.py`), после T01 принадлежат задаче из таблицы, а не T01. T15 может править чужие файлы при интеграции, но записывает каждую правку в отчёт с указанием владельца; цель `check` в `Makefile` дополняет T15.

| Задача | Файлы |
| --- | --- |
| T01 | `contracts/openapi.yaml`, `models.json`, `.env.example`, `.gitignore`, `Makefile`, `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/routers/__init__.py`, `backend/app/services/__init__.py`, `backend/tests/test_contract_routes.py`, `backend/tests/test_ownership.py`, `docs/OWNERSHIP.md`, `docs/TZ.md` |
| T02 | `backend/app/config.py`, `backend/app/db.py`, `backend/app/routers/health.py`, `backend/tests/conftest.py`, `backend/tests/test_core.py` |
| T03 | `frontend/` целиком, кроме `frontend/src/views/Generate/`, `frontend/src/views/Gallery/`, `frontend/src/views/Spending/`, `frontend/src/views/Profile/`, `frontend/src/views/Admin/` |
| T04 | `backend/app/services/pricing.py`, `backend/app/routers/models.py`, `backend/tests/test_pricing.py` |
| T05 | `backend/app/services/provider.py`, `backend/tests/test_provider.py`, `scripts/try_provider.py` |
| T06 | `backend/app/services/storage.py`, `backend/tests/test_storage.py` |
| T07 | `deploy/` целиком (Dockerfile, docker-compose.yml, design.caddy, backup/, deploy.sh, disk_alert.sh, README.md), `.dockerignore` |
| T08 | `backend/app/routers/auth.py`, `backend/app/routers/users.py`, `backend/app/deps.py`, `backend/app/manage.py`, `backend/tests/test_auth.py` |
| T09 | `backend/app/routers/generations.py`, `backend/app/services/jobs.py`, `backend/tests/test_generations.py` |
| T10 | `backend/app/routers/spending.py`, `backend/tests/test_spending.py` |
| T11 | `frontend/src/views/Generate/` |
| T12 | `frontend/src/views/Gallery/` |
| T13 | `frontend/src/views/Spending/`, `frontend/src/views/Profile/` |
| T14 | `frontend/src/views/Admin/` |
| T15 | `e2e/`, `scripts/load_check.py`, `scripts/security_check.sh`, `README.md` |
| T16 | сервер: `/opt/design-studio`, `.env` на сервере, блок Caddy на VDS, хук `/opt/backup/pre.d/design-studio.sh` (в репозитории файлов нет) |
| T17 | `docs/acceptance.md` (отчёт приёмки) |
