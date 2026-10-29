# Общий Makefile. Владелец — T01; цель check дополняет T15 (с записью в отчёте).
PY ?= python3
BACKEND := backend

.PHONY: dev check check-backend check-frontend install

install:
	cd $(BACKEND) && $(PY) -m pip install -e '.[dev]'

# Только один процесс: очередь и лимиты живут в памяти процесса.
dev:
	cd $(BACKEND) && $(PY) -m uvicorn app.main:app --reload --workers 1 --port 8000

check: check-backend check-frontend

check-backend:
	$(PY) -m openapi_spec_validator contracts/openapi.yaml
	cd $(BACKEND) && $(PY) -m ruff check . && $(PY) -m ruff format --check .
	cd $(BACKEND) && $(PY) -m pytest -q

# Фронтенд появляется в T03; до этого цель ничего не делает.
check-frontend:
	@if [ -f frontend/package.json ]; then \
		cd frontend && npx vue-tsc --noEmit && npm run --if-present lint && npx vitest run; \
	else echo "frontend/ ещё нет (T03), пропускаю"; fi
